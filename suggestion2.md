## 總體判斷

Plan agent 這一輪大方向正確，我會接受兩項主要修正：

1. **把 complete-set、split／merge 與抵押品占用提前到核心 domain model。**
2. **把極小實盤 canary 提前，把完整 queue simulator 延後。**

但有兩點需要修正：

* complete-set 是核心庫存原語，**但不是唯一的做市原語**，不能把整個策略縮減成「只掛 YES bid＋NO bid」。
* 不應在尚未測量真實延遲、成交率和 markout 前，就拍板策略只能靠 rewards 賺錢。

---

# 一、complete-set：接受提前，但修正策略表述

## 1. Plan agent 指出的硬約束是正確的

Polymarket 賣出 outcome token 時需要有相應 token balance／allowance；做市商通常先把抵押品 split 成等量 YES 和 NO，取得可供賣出的庫存，再於 CLOB 報價。官方也直接把 split、merge、redeem 定義為做市商的三個核心庫存操作。([Polymarket Documentation][1])

所以這些內容不能留到 M6：

* complete-set 數量；
* 可 merge 數量；
* split／merge 中的 pending 數量；
* 抵押品占用；
* outcome token 可用與保留餘額；
* split／merge 造成的 ledger event。

應從 M1/M2 進入 `inventory.py` 與 `market_spec.py`。

## 2. 但「flat MM 無法在單一 token 雙邊報價」不完全準確

更精確地說：

> 沒有 YES 庫存時，不能掛 YES ask；但可以先 split 少量抵押品取得 YES／NO，之後在 YES book 同時掛 bid 和 ask。

官方做市文件本身就以同一 token 的 bid／ask 作為基本雙邊報價範例，前提是已準備足夠 outcome-token inventory。([Polymarket Documentation][2])

因此原文件 M3 的「執行面可先在單一 token 報價」在技術上仍可行，但應改寫成：

> 第一版 domain model 必須理解 YES＋NO＋complete set；實盤 canary 可以在預先 split 的小額庫存下，只使用最少的實際訂單驗證執行流程。

## 3. 做市核心應是四條腿，而不是只有雙 bid

完整二元市場有四種基本操作：

| 實際訂單     | 經濟效果                |
| -------- | ------------------- |
| BUY YES  | 增加 YES 方向曝險         |
| SELL NO  | 透過處分 NO，增加 YES 方向曝險 |
| BUY NO   | 增加 NO 方向曝險          |
| SELL YES | 透過處分 YES，增加 NO 方向曝險 |

這是因為從一個 complete set 中賣出 NO 後，剩餘 YES 的有效成本為：

[
1-\text{NO sell price}
]

所以報價器最好不要直接先決定「下 YES bid」或「下 NO ask」，而應先決定：

```text
INCREASE_YES_EXPOSURE
DECREASE_YES_EXPOSURE
```

再由 execution allocator 根據以下條件選實際路徑：

* 可用 pUSD／collateral；
* 可用 YES／NO token；
* queue position；
* reward score；
* spread-after-markout；
* split／merge 成本與延遲；
* 當前方向庫存。

Polymarket 的 liquidity-reward 公式也把某市場的 bid 與互補市場的 ask 放入相同經濟側計分，支持這種「先抽象經濟方向，再映射實際訂單」的設計。([Polymarket Documentation][3])

## 4. complete-set 有兩個對稱循環

Plan agent 只提到：

[
bid_Y+bid_N<1
]

兩邊都成交後，以低於 1 的成本取得 complete set。

但另一側同樣重要：

[
ask_Y+ask_N>1
]

先 split 1 單位抵押品取得 YES＋NO，再將兩者以總價高於 1 的價格被動賣出，也是在實現 complete-set spread。

所以核心循環應是：

### Accumulation cycle

[
Edge_{\text{acquire}}
=====================

1-b_Y-b_N-\text{operational cost}
]

兩個 bid 都成交後 merge。

### Distribution cycle

[
Edge_{\text{distribute}}
========================

a_Y+a_N-1-\text{operational cost}
]

先 split，再等待兩個 ask 成交。

任何只有一條腿成交的狀態，才轉化為 directional inventory 和 adverse-selection 風險。

因此：

* **complete-set accounting、split／merge：核心功能，提前。**
* **跨 book 主動尋找失衡、neg-risk 多腿套利：仍可留在後期旁路。**

兩者不能混為同一個模組。

---

# 二、建議的 inventory domain model

不要硬編碼成 `USDC`；目前官方文件使用 pUSD 與 collateral adapter，domain 層應抽象為 `collateral`，由 adapter 處理實際資產。([Polymarket Documentation][4])

每個 condition 至少需要：

```text
InventoryState
├── collateral_free
├── collateral_reserved_for_bids
├── yes_free
├── yes_reserved_for_asks
├── no_free
├── no_reserved_for_asks
├── pending_yes
├── pending_no
├── pending_collateral
├── matched_unconfirmed_fills
├── pending_splits
├── pending_merges
└── confirmed_balances
```

派生量：

[
P=\min(Y,N)
]

其中 (P) 是可 merge 的 complete-set 數量。

[
D=Y-N
]

其中 (D) 是方向性庫存：

* (D>0)：淨 YES；
* (D<0)：淨 NO。

終局情境財富：

[
W_{\text{YES resolves}}=C+Y
]

[
W_{\text{NO resolves}}=C+N
]

因此最低終局價值為：

[
W_{\min}=C+\min(Y,N)
]

這比單純的 USDC notional cap 更符合預測市場風險。

Risk engine 還必須把 open orders 全部成交後的情境納入：

* 所有 YES bids 成交；
* 所有 NO bids 成交；
* 所有 YES asks 成交；
* 所有 NO asks 成交；
* 同方向最不利組合成交。

不能只根據「現在已成交庫存」批准下一張訂單。

---

# 三、edge 定位：不接受現在就拍板 reward-only

## 我的決定

> **第一版定位為「防守型、reward-aware 的被動做市」，但不預先宣告收益一定主要來自 rewards。**

原因是目前缺少三個實測數字：

* submit／cancel latency 的實際分布；
* 各市場 maker fill probability；
* 1s／5s／30s fill markout。

「家用 Windows＋Python 必然只能 reward harvesting」是一個合理假說，但不是已證實結論。部署位置、網路、SDK、批次送單、選市類型和 catalyst filter 都會影響結果。官方也建議使用 WebSocket、批次送單、即時撤除 stale quotes 及 GTD 避開已知事件。([Polymarket Documentation][2])

## 不應只建兩套互斥機器

應使用同一個目標函數：

[
EV_{\text{quote}}
=================

EV_{\text{core trading}}
+EV_{\text{maker rebate}}
+EV_{\text{liquidity reward}}
-\text{inventory penalty}
-\text{tail-risk penalty}
]

然後按實測結果將市場分類。

### A 類：core-positive

[
EV_{\text{core trading}}>0
]

Rewards 是額外收益，可以積極配置資金。

### B 類：subsidy-dependent

[
EV_{\text{core trading}}\leq0
]

但使用保守 haircut 後：

[
EV_{\text{core}}
+
EV_{\text{reward, conservative}}

> 0
> ]

可以交易，但必須：

* 獨立限制資金；
* 設定最大 core-loss budget；
* rewards 配置下降時立即停用；
* 不和 core-positive P&L 混報。

### C 類：reject

即使計入保守 rewards 後仍沒有正 EV，或尾部跳價足以消滅多日獎勵，不交易。

## 「貼著 max incentive spread 邊緣」不是正確 reward 策略

Liquidity reward 使用距離 adjusted midpoint 的非線性計分；接近允許的最外層 spread 時，分數會趨近零，而不是在邊界取得最佳報酬。收益還取決於相對於其他 maker 的 normalized share。([Polymarket Documentation][3])

因此 reward-aware quoter 應解：

[
\max_s
\left[
\text{expected reward score}(s)
-\text{expected markout loss}(s)
-\text{inventory cost}(s)
\right]
]

而不是固定掛在 `max_incentive_spread` 邊緣。

冷市場也不一定最好：

* toxicity 可能較低；
* 但 reward competition 可能集中；
* order book 很久不更新；
* 庫存成交後可能無法退出；
* 單次新聞跳價可能吞掉多日 rewards。

所以 M1 市場選擇應同時評估：

```text
reward_budget
estimated_competition
spread
trade_arrival_rate
book_update_rate
historical_jump_size
time_to_catalyst
inventory_exit_depth
```

---

# 四、canary 與 simulator：接受提前，但分成兩種 replay

## 我的決定

> **接受極小 canary 提前；完整 queue-model simulator 延後，但最小 deterministic replay 不能延後。**

需要區分：

### Canary 前必須完成

這不是績效回測，而是 correctness replay：

* raw event recorder；
* book snapshot＋delta 重建；
* WS reconnect marker；
* user fill 去重；
* order-state transition replay；
* ledger replay；
* split／merge event replay；
* process crash 後恢復；
* REST reconciliation。

同一份事件重播後，必須產生完全相同的：

* book；
* orders；
* fills；
* inventory；
* reservations。

這是安全要求，不是研究型 simulator。

### Canary 後才做

可以延後的是：

* queue-position estimator；
* counterfactual fill model；
* cancel-latency simulator；
* alternate quote-policy simulation；
* rewards counterfactual；
* 大規模參數搜尋。

我不同意把 full simulator 的投入條件定成「raw markout 必須已為正」。極小 canary 樣本會很少，markout 也可能高度偏態；更合理的 gate 是：

> 執行狀態可靠，沒有重複成交或庫存失真，且觀察到的 latency、fill 和 adverse-selection 分布沒有顯示策略必然不可行。

之後才決定 simulator 投入規模。

---

# 五、canary 不建議使用裸露的單腿 reward 報價

Plan agent 提議「最小、最安全的單腿 reward 帶報價」，但單腿不一定最安全：

* 它直接產生未配對方向曝險；
* 不能驗證 complete-set 回收；
* 無法測試雙腿庫存互動；
* 在部分極端價格市場，單邊 liquidity 甚至不計分；官方規則在 midpoint 低於 0.10 或高於 0.90 時要求雙邊 liquidity 才能得分。([Polymarket Documentation][3])

更好的 tiny canary：

1. 只選一個非臨近 catalyst 的 binary market。
2. 先 split 極少量 collateral，取得 YES＋NO。
3. 設定極低的 terminal worst-case loss。
4. 報價兩個**經濟方向**，實際使用兩張或四張訂單由 allocator 決定。
5. 全部使用 `postOnly=true`。
6. 啟用 heartbeat、GTD、stale-data kill 與最大單腿庫存。
7. complete-set 達門檻時 merge，驗證整個資金循環。
8. 同時量測 fill、cancel、markout 和 inventory recovery。

---

# 六、對新增風控條件的判斷

## 完全接受

* resolution／known-catalyst proximity halt；
* rolling markout breaker；
* tick-size-change 後 cancel＋requote；
* worst-case inventory band；
* unmatched-leg limit；
* split／merge pending-operation limit。

官方明確建議 GTD 用於已知事件、market close 或 resolution 前自動到期。([Polymarket Documentation][2])

## WS-staleness：需要改成雙層判斷

不能簡單用「N 毫秒沒有 book event」判定失效，因為冷門市場長時間沒有任何 order-book 變化可能是正常現象。

應同時監控：

1. **連線 liveness**：ping／pong、socket receive loop、server time。
2. **市場一致性**：定期 REST snapshot checksum、BBO、book hash、sequence／timestamp。
3. **決策資料 freshness**：最近一次完整 snapshot 或已驗證 delta 的時間。
4. **交易前 freshness guard**：每次 submit 前確認 book 未進入 uncertain state。

只要 book 進入 `STALE` 或 `UNSYNCED`，停止新報價並撤除現有訂單。

## GTD：不是主要 deadman switch

GTD 是有用的第二層保護，但 Polymarket 已有專門 heartbeat endpoint：若約 10 秒內未收到有效 heartbeat，另有最多約 5 秒緩衝，系統會取消所有 open orders。([Polymarket Documentation][5])

因此正確層級應是：

1. Heartbeat：程序／網路死亡時的全域 deadman。
2. GTD：避免訂單跨越已知 catalyst 或長時間殘留。
3. 主動 cancel：正常 quote replacement。
4. REST reconciliation：處理 response 遺失或未知狀態。

過短 GTD 會增加無謂重掛、失去 queue priority，並可能降低 reward sampling 覆蓋，所以不應把 GTD 當成每幾秒強制更新的唯一安全機制。

## Client-order-id：概念接受，但不要假設交易所有原生欄位

目前公開 order payload 沒有文件化的 `client_order_id`／idempotency key；訂單包含 salt，回傳的 order ID 是 order hash，系統也有 duplicate-order 錯誤。([Polymarket Documentation][6])

建議實作：

```text
local_intent_id
signed_order_hash
serialized_signed_payload
submit_attempt
exchange_order_id
reconciliation_status
```

流程：

1. 送單前先把 signed payload 和 hash 持久化。
2. response 遺失時，不要產生新 salt 再送一張新訂單。
3. 優先重送完全相同 payload。
4. 收到 duplicated response 時，轉入 reconciliation。
5. 查 open orders／trades 確認實際狀態。
6. 只有確定舊訂單不存在後，才建立新的 order intent。

---

# 七、還有一個需要加入 M0 的新 gate：wallet／signature type

截至 2026 年 5 月，Polymarket 官方 Python／TypeScript V2 client repository 有尚未關閉的問題回報，指出部分 `signatureType=3`／deposit-wallet 流程可能出現 API key 與 signer 不匹配或簽名失敗；這些是 issue 回報，並非官方已確認結論，但足以構成必須實測的風險。([GitHub][7])

因此 M0 必須先固定：

```text
wallet type
funder address
signer address
signature type
API-key ownership
split/merge relayer compatibility
order signing compatibility
```

並實際完成：

* post-only order；
* cancel；
* partial fill；
* user WS；
* split；
* merge；

整條鏈路。

否則可能完成大部分策略工程後，才發現目前 wallet／SDK 組合無法穩定送單。

---

# 八、修正後的里程碑

## M0：Exchange、wallet 與 protocol conformance

* wallet／signature-type 驗證；
* API key ownership；
* post-only；
* trade-side 語意；
* user／market WS；
* heartbeat；
* response-loss／duplicate-submit；
* partial fill；
* reconnect＋snapshot resync；
* split／merge 行為與延遲。

## M1：Market registry＋recorder＋domain model

從第一版就包含：

```text
condition_id
yes_token_id
no_token_id
collateral_asset
tick_size
fees
reward_parameters
yes/no balances
complete_set_quantity
directional_inventory
reserved balances
pending CTF operations
```

## M2：Execution／inventory／risk core

* immutable fill ledger；
* shadow／confirmed inventory；
* order state machine；
* CTF operation state machine；
* worst-case terminal risk；
* heartbeat deadman；
* GTD catalyst guard；
* stale／unsynced book kill；
* deterministic event replay。

## M2.5：極小 live canary

驗證：

* 真實 submit／cancel latency；
* fill probability；
* 1s／5s／30s markout；
* complete-set 回收；
* merge 循環；
* reward eligibility；
* inventory recovery time。

## M3：依 canary 結果決定 quoter 定位

而不是預先猜測：

* core-positive spread MM；
* subsidy-dependent reward MM；
* 混合配置；
* 或停止專案。

## M4：完整 simulator 與 toxicity

* queue model；
* counterfactual fills；
* OFI／CVD；
* cancel burst；
* reward-aware placement；
* policy replay。

---

## 最終拍板

對 plan agent 提出的兩個決定，我的答案是：

**第一，edge 定位不直接承認為純 reward harvesting；第一版採防守型 reward-aware 架構，透過 tiny canary 將市場分類成 core-positive、subsidy-dependent 或 reject，且 reward 報價要最佳化邊際分數與 markout，不能機械地貼在 max-incentive-spread 邊界。**

**第二，接受 canary 提前、完整 queue simulator 延後，但 canary 前必須完成 recorder、deterministic event replay、order state machine、fill ledger、complete-set／split／merge accounting、reconciler 與硬風控；canary 使用預先 split 的極小庫存測試兩個經濟方向，而不是裸露的單腿報價。**