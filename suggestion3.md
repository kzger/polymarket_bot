四個模型定義需要最後校正；修完即可直接進入 M0＋M0.5，不必再做第四輪完整設計。

## 1. Shadow markout 不一定「偏悲觀」

這是目前最需要更正的敘述。

若影子 bid 設在 (p)，只有當實際成交價嚴格低於 (p) 才假設成交，這可以視為較保守的 **fill eligibility**；但由此算出的 conditional markout 不一定是對真實策略的保守估計，因為：

* 嚴格穿價通常代表較強的 aggressive sweep，樣本容易偏向 toxic fills。
* 真實 queue position 會同時過濾毒性成交與良性成交，不保證實盤 markout 一定更好。
* 公開 feed 是聚合 L2，文件有 timestamp 和 book hash，但沒有文件化的單調 sequence number；斷線、重連或事件缺口期間，不能安全推定完整撮合順序。
* Market channel 的 `price_change` 主要對應新增／撤單，交易影響訂單簿時另有 `book` 和 `last_trade_price` 事件，因此 shadow engine 必須整合這些事件，而不能只看成交價是否穿越。([Polymarket Documentation][1])

所以不要把它命名為「悲觀真實 markout」，應明確命名為：

```text
strict_trade_through_shadow_markout
```

最好同時輸出兩個 fill envelope：

```text
Lower-bound fills:
只有在 activation latency 後嚴格穿過報價才算成交

Upper-bound fills:
成交觸及報價，且成交量足以消耗估計的 queue-ahead 時算成交
```

最後報告區間，而不是單一數字。

另外，不能只算 midpoint markout，至少要同時計算：

[
M_{\text{reference}}(\tau)
]

以 YES／NO 綜合 reference price 衡量資訊毒性，以及：

[
M_{\text{executable}}(\tau)
]

以 (\tau) 時點可實際平倉的對手價衡量真正退出損益。在 spread 較寬的市場，midpoint markout 可能看起來良好，但實際退出仍虧損。

---

## 2. Shadow engine 必須納入實測延遲，否則不是「真實延遲下的 markout」

`submit → WS ack` 和 `cancel → WS ack` 只能算部分延遲，不能直接代表 stale-quote exposure。

M0 至少要分開記錄：

```text
t0  本地開始送出 HTTP request
t1  收到 HTTP response
t2  收到 user WS order event
t3  收到 partial/full fill
t4  發出 cancel request
t5  收到 cancel response
t6  user WS／REST 確認不再 open
```

最重要的風險指標不是平均 cancel ack，而是：

```text
fills_after_cancel_request
fills_after_cancel_response
unknown-order-state duration
```

因為 cancel request 已發出，不代表在途訂單已不可能成交。User WS 是實時訂單與成交狀態來源，Market WS 則提供公開 book 和 trade event，兩者需要用本地 monotonic clock 對齊。([Polymarket Documentation][1])

因此 M0 和 M0.5 可以並行收資料，但 M0.5 的最終 shadow 結果必須在取得延遲分布後重新計算：

```text
quote_active_time = decision_time + sampled_submit_latency
quote_inactive_time = cancel_decision_time + sampled_cancel_effective_latency
```

零延遲 shadow 結果只能作為理想上限，不能拿來做 A／B／C 分類。

---

## 3. Split／merge 是第一類動作，但不是第五、六條「方向性腿」

Plan agent 說要把它們升級成第五、六條腿，概念上仍需修正。

定義：

[
D=Y-N
]

Split (q) 單位：

[
C\rightarrow C-q,\quad
Y\rightarrow Y+q,\quad
N\rightarrow N+q
]

所以：

[
\Delta D=q-q=0
]

Merge (q) 單位：

[
Y\rightarrow Y-q,\quad
N\rightarrow N-q,\quad
C\rightarrow C+q
]

同樣：

[
\Delta D=-q-(-q)=0
]

因此 split／merge 本身不增加或減少方向曝險；它們是 **inventory transformation／capital transformation**，官方也將 split、merge、redeem 定義為做市商的核心庫存操作。([Polymarket Documentation][2])

正確的 allocator 應分成兩層：

### Exposure router

決定要：

```text
INCREASE_YES_EXPOSURE
DECREASE_YES_EXPOSURE
```

### Inventory transformer

決定是否需要：

```text
SPLIT
MERGE
REDEEM
```

例如降低 YES exposure 的兩種經濟路徑：

[
\text{SELL YES at }b_Y
]

或者：

[
\text{BUY NO at }a_N+\text{MERGE}
]

第二條路徑的淨回收為：

[
1-a_N-\text{CTF/operational costs}
]

所以 execution allocator 可以比較：

[
b_Y
\quad\text{vs}\quad
1-a_N-\text{costs}
]

但 directional change 是由 BUY NO 造成，merge 只是消除配對庫存並釋放 collateral。

建議模組切分為：

```text
EconomicRoute
├── BUY_YES
├── SELL_NO
├── BUY_NO
└── SELL_YES

InventoryTransformation
├── SPLIT
├── MERGE
└── REDEEM
```

可以有 composite plan，例如 `BUY_NO_THEN_MERGE`，但不要在 domain model 中把 merge 誤當成方向性交易腿。

---

## 4. unmatched-leg 是主要方向風險，但不是唯一風控限制

Plan agent 說「風控要 bound 的不是總庫存，而是最大未配對方向庫存」方向正確，但「總庫存不重要」會走得太遠。

Complete set 雖然終局 payoff 有界，也可以 merge 回 collateral，但仍然存在：

* 資金占用；
* pending merge／split；
* relayer 或鏈上操作失敗；
* allowance／balance 不一致；
* 已被 open asks 保留、暫時無法 merge 的 token；
* 大量配對庫存造成的資金周轉限制。

官方將 merge 描述為釋放資本、降低 exposure 的庫存操作，這也表示 paired inventory 不是零成本狀態。([Polymarket Documentation][2])

所以 risk engine 至少需要兩組獨立上限：

```text
directional_unmatched_limit
paired_inventory_cap
```

還要加上：

```text
collateral_reserved_cap
pending_ctf_operation_cap
unconfirmed_fill_cap
```

此外，不要只測「all orders fill」。真正的 worst case 通常是某個子集合成交。

設當前方向庫存為 (D_0)：

[
U_+
===

Q_{\text{BUY YES}}
+
Q_{\text{SELL NO}}
]

[
U_-
===

Q_{\text{BUY NO}}
+
Q_{\text{SELL YES}}
]

忽略額外限制時，可達方向庫存區間為：

[
D_{\min}=D_0-U_-
]

[
D_{\max}=D_0+U_+
]

風控應保證：

[
D_{\min}\ge -D_{\text{limit}}
]

[
D_{\max}\le D_{\text{limit}}
]

兩條互補訂單全部成交可能使方向風險互相抵銷，但只成交其中一側才通常是最危險情境。

---

## 5. M0.5 不能直接完成 A／B／C 最終分類

Recorder＋shadow markout 很適合作為早期篩選器，但不能單獨產出可靠的最終分類。

尤其 rewards 是相對分配：官方公式根據每個參與者在市場中的相對 (Q_n) share 計算，並依 adjusted midpoint 距離、size、雙邊程度及採樣結果評分。僅從公開 L2 可以估計 qualifying depth 和競爭程度，但無法完整知道自己的實際 normalized reward share。([Polymarket Documentation][3])

因此 M0.5 應輸出：

```text
core-positive candidate
subsidy-dependent candidate
reject candidate
```

而不是正式 A／B／C。

正式分類仍需 tiny live canary：

* 實際 fill probability；
* 真實 queue selection；
* latency-adjusted markout；
* 實際 reward eligibility／earnings；
* 單腿庫存回收時間。

---

# 建議的 M0.5 最終規格

M0.5 可以立即做，但建議改成以下交付物：

1. **Recorder／book reconstruction**

   * 原始 WS payload；
   * socket arrival order；
   * server timestamp；
   * local monotonic timestamp；
   * reconnect／unsynced markers；
   * periodic REST snapshot verification。

2. **Latency-calibrated shadow quotes**

   * 多個報價距離，不只 BBO；
   * submit activation delay；
   * cancel effective delay；
   * catalyst／stale windows 排除。

3. **Fill bounds**

   * strict-cross lower-bound；
   * touch＋queue-ahead upper-bound；
   * partial-fill size bounds。

4. **Markout**

   * 1s／5s／30s reference markout；
   * executable unwind markout；
   * complementary YES／NO consistency；
   * markout 按市場狀態和 flow regime 分組。

5. **初步策略輸出**

   * fill-opportunity rate；
   * conditional markout；
   * spread-after-executable-markout；
   * hypothetical unmatched-inventory path；
   * reward qualifying-score proxy；
   * candidate／reject，而非正式獲利認定。

## 最終決定

**接受立即啟動 M0 conformance＋M0.5 recorder/shadow-markout，不需要再先寫一份大型設計文件；但需把 shadow markout 改成含延遲的上下界篩選器、把 split／merge 建模為第一類庫存轉換而非方向性腿、將風控從單純 unmatched limit 擴充為方向庫存＋配對資金占用雙限制，並把 M0.5 的 A/B/C 降級為候選分類，正式分類留到 tiny live canary 後。**