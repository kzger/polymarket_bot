## 我的決策

**不要在現有策略骨架上做全面漸進式重構；建議採用「交易核心重寫、周邊基礎設施選擇性重用」的方式，在同一 repo 建立獨立的 `mm_v2`，舊系統只作為參考與對照。**

原因是目前需要改變的不是幾個指標，而是系統的核心不變量：

* 資料主鍵要從單一 `token_id` 改為 `condition_id → outcomes/tokens`。
* 持倉要從 USDC notional 改為 fill 驅動的 share ledger。
* 訂單管理要從「下單＋逾時撤單」改成 event-driven order state machine。
* 回測要從價格 K 線邏輯改成 L2、逐筆成交、queue 與 cancel latency replay。
* CVD、風控、報價與績效衡量全部依賴上述新模型。

在這種情況下，逐檔修補容易保留舊假設，最危險的是出現「庫存、訂單、成交三套狀態彼此不一致」。

---

## 對四個 binding constraints 的判斷

### 1. Post-only：已確認存在，不再是阻塞項

Polymarket 現在有原生 `postOnly` 參數，只支援 GTC/GTD；若訂單到達撮合引擎時會立即成交，就會被拒絕，而不是成為 taker。([Polymarket Documentation][1])

因此不要用「掛在 spread 內側」模擬 post-only，應直接使用：

```text
orderType = GTC 或 GTD
postOnly = true
```

但要注意，post-only 只保證**進場時不主動成交**；成功進入 book 後，被 taker 成交正是正常行為。它不能消除 stale quote、撤單延遲或 adverse selection。

此外，現有 `py-clob-client` wrapper 是否已暴露 `postOnly`，只是 adapter 問題，不是交易所能力問題。若舊 wrapper 不支援，直接擴充 REST payload 或替換 adapter 即可。

### 2. Market WS＋User WS：已確認存在

官方提供：

* Market channel：L2 snapshot、price-level change、best bid/ask、tick-size change、trade event。
* User channel：自己的 order placement、partial fill、cancel，以及 trade 的 `MATCHED → MINED → CONFIRMED/FAILED` 狀態。([Polymarket Documentation][2])

所以庫存架構應分兩層：

* **Trading/shadow inventory**：收到 `MATCHED` 立即更新，用於即時風控與報價。
* **Settlement inventory**：收到 `CONFIRMED` 後更新最終狀態；若 `FAILED`，執行 rollback 或 REST reconciliation。

不能等 `get_positions` 輪詢後才更新庫存。

同時要避免 user channel 的 `trade` event 和 `order UPDATE` 重複計入同一筆成交，必須以 trade ID、order ID 與累積 `size_matched` 做冪等去重。

### 3. Trade side：仍應做受控實測

Market WS 的 `last_trade_price` 明確包含 `side`、price、size；User WS 也包含 `side`、maker orders、taker order ID 等欄位。([Polymarket Documentation][2])

但目前文件範例沒有足夠明確地用一句話保證公開 `last_trade_price.side` 就是你所需要的 aggressor side。因此不建議直接把它寫死成：

```text
BUY = buyer initiated
SELL = seller initiated
```

應建立一個 protocol conformance test：

1. 記錄交易前 book。
2. 用受控小額訂單主動買入。
3. 比對 market WS 的 `side`。
4. 比對 user WS 的 `side`、`trader_side` 與 taker order ID。
5. 再用主動賣出重做一次。
6. 將測試結果固化成 regression test。

在完成此測試前，CVD 模組應允許 `side_semantics` 可配置，而不是散落在策略程式內。

### 4. Rewards：規格已足夠，不是阻塞項

需要把兩種獎勵分開：

* **Maker rebates**：只針對實際被成交的 maker liquidity，依 fee-equivalent 及該市場內的相對份額分配。
* **Liquidity rewards**：依距離 adjusted midpoint、掛單數量、雙邊程度、`min_incentive_size`、`max_incentive_spread` 及隨機分鐘採樣計算。([Polymarket Documentation][3])

所以 plan agent 所說的「距離 band × size × time」只描述 liquidity rewards，不能用來估算 maker rebate。

建議：

* 市場 metadata ingestion 從第一版就保存 rewards 參數；
* 報價最佳化到後期才使用 rewards；
* P&L 永遠分成 `core_trading_pnl`、`maker_rebate`、`liquidity_reward` 三項；
* 不允許 rewards 掩蓋負的 spread-after-markout。

Liquidity reward 是每分鐘隨機採樣並在 epoch 內累積，不能簡單將「掛單秒數」線性換算成收益。([Polymarket Documentation][3])

---

## SDK 的建議

不建議將新交易核心直接綁死在現有 `py-clob-client`。

官方的 `py-clob-client-v2` 已建議新專案轉向統一的 `py-sdk`，但目前官方 `py-sdk` 仍標示為 beta。([GitHub][4])

因此應採 ports-and-adapters：

```text
Strategy / Risk / Inventory / Order State Machine
                    │
              ExchangePort
       ┌────────────┴────────────┐
       │                         │
ClobRestAdapter             ClobWsAdapter
```

核心只依賴自己的介面：

```text
submit_order()
cancel_order()
cancel_market_orders()
fetch_open_orders()
fetch_book_snapshot()
subscribe_market_events()
subscribe_user_events()
send_heartbeat()
```

這樣可以先使用現有 wrapper，之後替換為新 SDK 或直接 REST/WS，而不必重寫策略與風控。

---

## 建議重用與重寫邊界

### 可以重用

前提是已有測試且沒有混入舊交易假設：

* 設定檔與 secrets 管理。
* logging、metrics、alerting。
* deployment、Docker、程序管理。
* API authentication、簽名與基本 REST wrapper。
* 通用 retry、rate-limit、serialization 工具。
* 市場 discovery 的部分查詢程式。

### 應重寫

* `MarketData`／`watched_markets`。
* `PositionTracker`。
* 現有 CVD。
* `order_manager` 的核心狀態管理。
* strategy loop。
* risk engine。
* backtesting execution model。
* P&L attribution。

其中現有 `PositionTracker` 不應只補上 `update_fill()`；因為它的 notional 資料模型本身就不適合作為做市庫存帳本。

---

## 新系統應採用的核心結構

```text
mm_v2/
├── domain/
│   ├── market_spec.py
│   ├── order.py
│   ├── fill.py
│   ├── inventory.py
│   └── risk.py
├── feeds/
│   ├── market_ws.py
│   ├── user_ws.py
│   ├── book_builder.py
│   └── recorder.py
├── execution/
│   ├── exchange_port.py
│   ├── clob_adapter.py
│   ├── order_state_machine.py
│   └── reconciler.py
├── strategy/
│   ├── fair_value.py
│   ├── quoter.py
│   ├── inventory_skew.py
│   └── toxicity.py
├── accounting/
│   ├── inventory_ledger.py
│   ├── pnl.py
│   └── markout.py
├── replay/
│   ├── event_reader.py
│   ├── queue_model.py
│   └── simulator.py
└── app/
    ├── recorder_main.py
    ├── paper_mm_main.py
    └── live_mm_main.py
```

---

## 建構順序的修正

Plan agent 的順序基本正確，但我會作兩項重要調整。

### 第一：先做 protocol spike，再改庫存

不要直接在舊系統接 `update_fill()`。先完成最小的交易所行為驗證：

* post-only crossing rejection；
* market WS snapshot 與 delta；
* user WS placement、partial fill、cancel；
* trade side 語意；
* WS 斷線重連；
* snapshot resync；
* 重複事件去重；
* `MATCHED/CONFIRMED/FAILED` 狀態處理。

通過後再把這些行為固化到新核心。

### 第二：Recorder 與 live event handlers 必須共用

官方文件目前提供即時 L2 WebSocket，而歷史資料介面主要是 price history，不應假設存在可直接取得的官方歷史 L2 replay。([Polymarket Documentation][2])

因此 recorder 應保存原始事件：

```text
exchange_timestamp
local_receive_timestamp
monotonic_timestamp
channel
condition_id
asset_id
event_type
raw_payload
connection_id
reconnect_marker
```

回測時直接將相同事件重新送入：

* `BookBuilder`
* `InventoryLedger`
* `OrderStateMachine`
* `Quoter`

不要另寫一套與 live 不同的策略回測邏輯。

---

## 建議的實際里程碑

### M0：Exchange conformance

完成所有 API／WS 行為測試，不交易策略。

通過條件：

* 能證明 post-only 不會成為 taker；
* 能正確識別自己的 partial fill；
* 斷線後可以重建 book 與 open orders；
* 同一 fill 不會重複入帳；
* trade side 語意已用實測固定。

### M1：Recorder＋Market Registry

市場資料模型至少包含：

```text
condition_id
yes_token_id
no_token_id
tick_size
neg_risk
fees_enabled
fee_schedule
min_incentive_size
max_incentive_spread
market_status
```

第一版可只支援 binary market，不必立即泛化到所有 neg-risk 事件。

### M2：Execution＋Inventory Core

訂單狀態至少包含：

```text
INTENT
PENDING_NEW
LIVE
PARTIALLY_FILLED
PENDING_CANCEL
CANCELED
FILLED
REJECTED
UNKNOWN
```

`UNKNOWN` 很重要：斷線、timeout 或 response 遺失時，不能武斷地認為訂單失敗。

庫存必須由 immutable fill ledger 派生，而不是直接修改一個總數。

### M3：Paper market maker

從第一天就讀取 YES 和 NO 兩本 book。

執行面可以先只在一個 token 報價以降低複雜度，但 fair value、庫存與風控模型必須已理解兩個 token，不能先做真正的「YES-only 市場模型」。

初版只需要：

* microprice/reference price；
* 固定 minimum half-spread；
* 線性 inventory skew；
* post-only；
* stale-data cancel；
* max inventory；
* markout 記錄。

### M4：小額 live canary

只有完成 paper execution 後才用最小尺寸實盤，驗證：

* 實際 fill probability；
* cancel latency；
* order rejection；
* user WS 完整性；
* 1s／5s／30s markout；
* 庫存回收速度。

### M5：Toxicity

再加入：

* OFI；
* event-time CVD；
* cancel burst；
* aggressive trade streak；
* BBO depletion；
* markout regime。

它們先用於 `widen/skew/cancel/size`，不要直接產生方向性市價訊號。

### M6：Rewards 與套利旁路

最後加入：

* liquidity reward placement；
* maker rebate attribution；
* complete-set scanner；
* neg-risk scanner。

---