# mm_v2 — Polymarket-Native Market Making · Plan & Spec

**Status:** design converged (3 review rounds + synthesis). Build not started.
**This file is the single source of truth.** Other agents: read this fully before touching code. If you disagree, edit the "Open decisions" section with a proposal — do **not** silently diverge in code. Freeze the two contracts in §10 before parallel work.

Last updated: 2026-06-30 (contract reviews #1–#4 incorporated: CLOB V2 facts verified; Contracts #1/#1b/#2/#3/#4 frozen — recorder envelope + parsed union [per-asset price_change, WS-vs-REST trade split, MakerOrderFill], ports incl. cancel/heartbeat/restricted-modes, balance basis, settlement identity).

---

## 1. Background & decision

The original repo (`strategies/`, `bot/`, `backtesting/`, `deploy/`) is an ETH-signal bot: MACD/RSI/CVD computed on **Binance ETH/USDT candles**, placing limit orders on **arbitrary Polymarket tokens**. This is a signal/target mismatch and is being **retired as legacy reference**.

**New direction (user intent, confirmed):** trade *arbitrary* Polymarket markets using strategies derived from *Polymarket's own data*. First system = **defensive, reward-aware, toxicity-filtered, inventory-skewed passive market making**, built as a **clean rewrite in `mm_v2/`** (not a patch of the old scaffold — the old `PositionTracker`/`MarketData`/`order_manager` carry trading assumptions that don't fit).

**Edge positioning is UNDECIDED on purpose.** Do not hard-code "reward-only." We measure first (§7, §9), then classify each market as `core-positive` / `subsidy-dependent` / `reject`.

---

## 2. Scope of v1

**In:** binary markets (single `condition_id` → YES/NO token pair); post-only passive quoting; fill-driven inventory; complete-set split/merge/redeem as core inventory ops; dual-limit risk; recorder + latency-calibrated shadow markout; tiny live canary.

**Out (deferred):** neg-risk multi-outcome arbitrage; cross-market active imbalance hunting; full queue-position simulator; large parameter sweeps; OFI/CVD as directional entry signals (toxicity signals are skew/widen/cancel **only**).

---

## 3. Core design invariants (agreed; do not violate without editing §11)

1. **Data primary key = `condition_id → {yes_token_id, no_token_id}`.** Always reason about **both** books. Never key the system on a single `token_id`.
2. **Inventory is derived from an immutable fill ledger**, never by mutating a running total. Two layers:
   - *Shadow/trading inventory* — updated on `MATCHED` (used for live risk & quoting).
   - *Settlement inventory* — updated **only** on `CONFIRMED`.
   - **Trade settlement status set (frozen, verified vs official User Channel docs) = `MATCHED → MINED → CONFIRMED | FAILED`, with a non-terminal `RETRYING` loop** (tx reverted/reorged, operator resubmitting). **Terminal = `CONFIRMED` / `FAILED` only.** On `RETRYING`: do **not** roll back shadow inventory and do **not** promote to settlement — hold as unconfirmed exposure (counts against `unconfirmed_fill_cap`) and enter an **age-based reconcile/breaker**. Roll back / REST-reconcile only on `FAILED`.
   - **Settlement identity (Contract #4):** a single trade can be split across multiple on-chain transactions (gas limits), so distinguish **logical-fill key = `(trade_id, order_id/maker_order_id)`** from **settlement-bucket key = `(trade_id, bucket_index, transaction_hash?)`**, reconciled via `match_time`. `CONFIRMED`/`FAILED`/`RETRYING` MUST be explicitly tagged as *logical-trade* vs *bucket* status; until a logical trade is proven terminal across **all** its buckets, treat it as conservative unconfirmed exposure (no early settlement promote, no partial rollback at wrong granularity).
   - Idempotent dedup: live/logical fills by `(trade_id, order_id, cumulative size_matched)`; settlement buckets by `(trade_id, bucket_index, transaction_hash?)` when REST/on-chain metadata exists.
3. **Allocator is two layers:**
   - **Exposure router** decides economic direction: `INCREASE_YES_EXPOSURE` / `DECREASE_YES_EXPOSURE`.
   - **Inventory transformer** decides `SPLIT` / `MERGE` / `REDEEM`.
   - `SPLIT`/`MERGE` are **delta-neutral (ΔD = 0)** capital/inventory transforms, **NOT** directional legs. Composite plans allowed (e.g. `BUY_NO_THEN_MERGE`), but the directional change is owned by the trade leg, not the merge.
4. **Complete-set is a core inventory primitive from M1**, not a late arb side-quest:
   - Accumulation: passive `b_Y + b_N < 1` → both fill → `MERGE` → realize `1 − (b_Y+b_N) − cost`.
   - Distribution: `SPLIT` → passive `a_Y + a_N > 1` → both fill.
   - Any **single-leg** fill = directional inventory + adverse-selection exposure (the thing we fear).
5. **post-only quoting.** Polymarket has native `postOnly` (GTC/GTD only); crossing orders are *rejected*, not taken (verify in M0). post-only does **not** remove stale-quote / cancel-latency / adverse-selection risk.
6. **Order lifecycle is an explicit state machine** incl. `UNKNOWN` (never assume a lost-response order failed). A reconciler resolves `UNKNOWN` via REST + user WS.
7. **Deadman hierarchy:** heartbeat endpoint (primary global deadman; ~10s + ~5s buffer cancels all — verify in M0) > GTD catalyst/expiry guard > active cancel (normal requote) > REST reconciliation. GTD is **not** the primary deadman; do not use ultra-short GTD as a requote loop.
8. **Recorder and live share the same event-handling code.** Backtest = replay the *same* recorded events through the *same* BookBuilder/Ledger/OrderStateMachine/Quoter. No separate backtest strategy logic. (This is what fixes the legacy "backtest = self-deception" problem.)
9. **P&L is always attributed into three buckets:** `core_trading_pnl`, `maker_rebate`, `liquidity_reward`. Rewards may **never** mask a negative spread-after-markout. Core and subsidy P&L are reported separately.
10. **Collateral is abstracted** (`collateral`, via adapter — pUSD/USDC handled by the adapter), never hard-coded as `USDC` in the domain layer.

---

## 4. Domain model (pure, no I/O — implement & unit-test first)

### 4.1 MarketSpec (per condition)
```
condition_id
yes_token_id, no_token_id
collateral_asset
tick_size                 # may change live → requote on tick-size-change event
neg_risk (bool)           # v1: binary only; keep field for later
fees_enabled, fee_schedule
reward_params: { min_incentive_size, max_incentive_spread, ... }
market_status
```

### 4.2 InventoryState (per condition; derived from fill ledger + CTF ops)
```
collateral_free
collateral_reserved_for_bids
yes_free, yes_reserved_for_asks
no_free,  no_reserved_for_asks
pending_yes, pending_no, pending_collateral
matched_unconfirmed_fills
pending_splits, pending_merges
confirmed_balances
```
Derived:
```
P = min(Y, N)        # mergeable complete-set quantity
D = Y − N            # directional inventory (D>0 net YES, D<0 net NO)
W_YES_resolves = C + Y
W_NO_resolves  = C + N
W_min = C + min(Y, N)      # worst-case terminal value — use this, not USDC notional
```
**Balance basis (frozen — Contract #3).** `C/Y/N` in the formulas above use **`shadow_owned_total`** = `confirmed_balances` + `reserved_for_asks` + `MATCHED`-but-unconfirmed fills, and **exclude** non-terminal CTF pending (`pending_splits` / `pending_merges`). Rationale: risk must treat tokens committed to resting asks and matched fills as owned, but must never credit a split/merge that could still fail. A **separate `available_to_order` basis** (free, unreserved, terminal-only) governs new-order capacity — never use it for `D/P/W_min`, and never use `shadow_owned_total` for order capacity. Pending split/merge contribute only via a **conservative failure-state projection** (assume the leg you would lose; never count collateral and outcome tokens for the same pending op simultaneously). All `D/P/W_min` consumers (risk, quoter, allocator) MUST read the same basis accessor — no ad hoc recomputation from raw fields.

### 4.3 Economic routing (two-layer allocator)
```
ExposureRoute      = { BUY_YES, SELL_NO, BUY_NO, SELL_YES }
InventoryTransform = { SPLIT, MERGE, REDEEM }
CompositePlan      = e.g. BUY_NO_THEN_MERGE
```
Exposure router emits `INCREASE_YES` / `DECREASE_YES`. Execution allocator picks the concrete path by comparing e.g. `b_Y` vs `1 − a_N − costs`, conditioned on: available collateral, available YES/NO tokens, queue position, reward score, spread-after-markout, split/merge cost+latency, current directional inventory.

### 4.4 Order & lifecycle
```
states: INTENT → PENDING_NEW → LIVE → PARTIALLY_FILLED → FILLED
                              ↘ PENDING_CANCEL → CANCELED
        any → REJECTED
        any → UNKNOWN (lost response / timeout) → reconcile → resolved state
```
Submit idempotency (no native client_order_id): persist `local_intent_id`, `signed_order_hash`, serialized signed payload, `submit_attempt`, `exchange_order_id`, `reconciliation_status`. On lost response: **resend the identical signed payload** (do not re-salt); on duplicate response → reconcile via open-orders/trades; only create a new intent after confirming the old one does not exist.

---

## 5. Architecture (ports & adapters)

Core depends only on its own `ExchangePort` / `CtfPort` interfaces, so the SDK (current `py-clob-client`, future `py-sdk` beta) can be swapped without touching strategy/risk/inventory.

```
ExchangePort:  submit_order, cancel_order, cancel_market_orders,
               fetch_open_orders, fetch_book_snapshot,
               subscribe_market_events, subscribe_user_events, send_heartbeat
CtfPort:       split, merge, redeem, fetch_balances
```

### Directory
```
mm_v2/
├── PLAN.md                 # this file
├── domain/                 # pure, no I/O (WS-B)
│   ├── market_spec.py
│   ├── order.py
│   ├── fill.py
│   ├── inventory.py        # ledger → InventoryState; P, D, W_min
│   ├── routing.py          # ExposureRoute / InventoryTransform / allocator
│   └── risk.py             # dual-limit + reachable-interval checks
├── feeds/                  # read-only (WS-A)
│   ├── market_ws.py
│   ├── user_ws.py
│   ├── book_builder.py     # L2 snapshot+delta; mark UNSYNCED gaps
│   └── recorder.py         # raw event capture (schema = Contract #1)
├── execution/              # (WS-D, needs creds for live)
│   ├── exchange_port.py    # interface (Contract #2)
│   ├── ctf_port.py
│   ├── clob_adapter.py     # py-clob-client REST+WS impl
│   ├── order_state_machine.py
│   └── reconciler.py
├── strategy/
│   ├── fair_value.py       # microprice / reference (YES+NO consistent)
│   ├── quoter.py
│   ├── inventory_skew.py
│   └── toxicity.py         # OFI / event-CVD → skew/widen/cancel only
├── accounting/
│   ├── inventory_ledger.py
│   ├── pnl.py              # core / rebate / reward buckets
│   └── markout.py          # reference + executable-unwind markout
├── replay/                 # (after canary)
│   ├── event_reader.py
│   ├── queue_model.py
│   └── simulator.py
└── app/
    ├── recorder_main.py        # M0.5 read-only entry
    ├── conformance_main.py     # M0 (needs creds)
    ├── paper_mm_main.py
    └── live_mm_main.py
```

---

## 6. Risk model

Two **independent** limits + supporting caps:
```
directional_unmatched_limit     # primary tail risk: single-leg fills
paired_inventory_cap            # paired set is NOT free: capital, pending CTF, relayer-fail,
                                #   asks reserving tokens so they can't merge, turnover
collateral_reserved_cap
pending_ctf_operation_cap
unconfirmed_fill_cap
```
`unconfirmed_fill_cap` is measured on **gross** outstanding unsettled-fill quantity (never the net of offsetting fills — a still-unsettled BUY_YES + SELL_YES do not cancel). `InventoryState.matched_unconfirmed_fill_gross` carries it, populated by the ledger fold via `domain.fill.gross_unconfirmed_fill_quantity` (deduped by logical-fill key; terminality aggregated across **all** of a trade's buckets per §3.2). It is a **cap-only** basis, deliberately outside the frozen `shadow_owned_*` / `available_*` accessors (Contract #3).

The **fill-based** caps (`unconfirmed_fill_cap` gross, and `paired_inventory_cap`) are projected on the **reachable** set in `assess_new_order` — the resting orders in `pending_by_route` plus the candidate — because they accrue at fill (same basis as the directional interval): gross sums all reachable-route fills; paired adds reachable BUY fills per outcome side. `collateral_reserved_cap` is the exception — collateral is reserved at *placement*, so resting bids are already counted and only the candidate's marginal reservation is projected.

**Worst case = a *subset* of orders filling, not all.** With current `D₀`:
```
U₊ = Q(BUY_YES) + Q(SELL_NO)
U₋ = Q(BUY_NO)  + Q(SELL_YES)
reachable D ∈ [D₀ − U₋, D₀ + U₊]
require: D₀ − U₋ ≥ −D_limit  and  D₀ + U₊ ≤ D_limit
```
Approving the next order must consider this reachable interval, not just already-filled inventory.

**Hard kill conditions:** resolution/known-catalyst proximity halt (widen→withdraw); rolling markout breaker; tick-size-change → cancel+requote; book `STALE`/`UNSYNCED` → pull quotes; REST-heartbeat loss → exchange cancels all open orders (user-global; rely on it but also self-cancel). The **REST heartbeat deadman** and **market/user-WS PING/PONG liveness** are two independent channels — a healthy WS does not imply a healthy heartbeat chain (or vice versa); monitor both.

**WS-staleness is layered** (cold markets are legitimately quiet — do not use "N ms no book event" alone):
1. connection liveness (ping/pong, recv loop, server time)
2. market consistency (periodic REST snapshot checksum / BBO / book hash / timestamp)
3. decision-data freshness (age of last verified snapshot/delta)
4. pre-trade freshness guard (re-check before every submit)
→ on `STALE`/`UNSYNCED`: stop new quotes, cancel resting.

---

## 7. M0.5 measurement spec (read-only; the cheap go/no-go)

No credentials, no orders, public market WS only. Deliverables:

1. **Recorder / book reconstruction:** raw WS payload, socket arrival order, server ts, local monotonic ts, reconnect/unsynced markers, periodic REST snapshot verification. Capture **enough L2 depth** (executable-unwind markout needs the full opposite side, not just BBO). Mark gaps where match order can't be inferred (no documented monotonic sequence number) as `UNSYNCED` and **exclude from markout stats**.
2. **Latency-calibrated shadow quotes:** multiple quote distances (not just BBO); apply `submit activation delay` and `cancel effective delay` sampled from M0; exclude catalyst/stale windows.
3. **Fill bounds (report a range, not one number):**
   - lower bound = strict trade-through after activation latency (`strict_trade_through_shadow_markout`)
   - upper bound = touch + trade size consumes estimated queue-ahead
   - partial-fill size bounds
4. **Markout:** 1s/5s/30s **reference** markout (YES/NO-consistent ref price) **and executable-unwind** markout (price you could actually exit at — in wide spreads ref looks fine while exit loses); grouped by market state / flow regime.
5. **Preliminary output (candidate, NOT final classification):** fill-opportunity rate, conditional markout, spread-after-executable-markout, hypothetical unmatched-inventory path, reward qualifying-score proxy → `core-positive candidate` / `subsidy-dependent candidate` / `reject candidate`.

Zero-latency shadow = ideal upper bound only; never used for classification. Final A/B/C requires the tiny live canary (rewards are a *relative* allocation — your normalized share is not observable from public L2).

---

## 8. Exchange facts & unknowns to pin in M0

Confirmed (per Polymarket docs; re-verify on our wallet in M0): native `postOnly` (GTC/GTD); Market WS (L2 snapshot, price_change, best bid/ask, tick-size change, last_trade_price) + User WS (placement, partial fill, cancel, `MATCHED→MINED→CONFIRMED/FAILED`); heartbeat auto-cancel; liquidity rewards = nonlinear score by distance to adjusted midpoint × size × two-sidedness × normalized share, minute-sampled; markets with midpoint <0.10 or >0.90 require two-sided liquidity to score; split/merge/redeem are the documented MM inventory ops.

Must test on our actual wallet/SDK (do not assume):
- wallet type / funder / signer / **signatureType** (reported signatureType=3 / deposit-wallet signing issues — must validate the full sign→submit→cancel→split→merge chain end-to-end before any strategy work);
- exact trade-side semantics (controlled buy/sell probe → freeze as regression test; keep `side_semantics` configurable until proven);
- full latency chain `t0..t6` and `fills_after_cancel_request/response`, `unknown-state duration`.

**Verified against CLOB V2 docs (review #1, 2026-06-30) — newly confirmed facts:**
- **CLOB V2 is live (Apr 28 2026); V1 SDKs/orders are no longer supported; `pUSD` replaced `USDC.e`; open orders were wiped at migration.** ⇒ the v1 `py-clob-client` in `requirements.txt` is **not viable** for live; must use **`py-clob-client-v2` / unified `py-sdk` (beta) / `rs-clob-client`** — see §11 protocol-stack decision.
- **Signature types** = `0 EOA / 1 POLY_PROXY / 2 POLY_GNOSIS_SAFE / 3 POLY_1271` (deposit wallet, ERC-1271; the onboarding path for **new** API users). v1 SDK only supports 0/1/2.
- **Order insert statuses** = `matched | live | delayed | unmatched` (frozen into Contract #2). `delayed`/`unmatched` arise from per-market taker delays (selected crypto/finance up-down + sports); **during the delay the order is pending and cannot be canceled, and may be rejected when the delay expires** → the cancel/deadman and reachable-interval logic must treat a delayed order as live, uncancelable exposure.
- **⚠️ Active SDK blocker — `py-clob-client-v2` issue #70:** L1 auth binds the API key to the EOA, not the deposit wallet, so **type-3 order placement currently fails** (`"the order signer address has to be the address of the API KEY"`, also #64/#75/#77). Root cause: API-key registration (`createApiKey`/`deriveApiKey`) does **not** EIP-1271-wrap the L1 auth in **any** current SDK — #70 reproduced on `py-clob-client-v2` 1.0.1 **and** `rs-clob-client-v2` 0.5.1 (TS #64 too) — so the key binds to the EOA while orders set signer = deposit wallet. **There is no default-working type-3 client today; Rust is a candidate, not a known-good path.** Existing **proxy/Safe accounts (type 1/2) are unaffected and still work** — the only confirmed-working fallback for a canary. ⇒ **M0's first gate, before any strategy work**, is to validate the full chain `create/derive api key → sign → postOrder → cancel → user WS` per candidate (`py-sdk` / `py-clob-client-v2` / `ts-sdk` / `rs-clob-client-v2` / direct REST with a hand-wrapped 1271 L1 header). Re-check #70 at M0 start.
- **Relayer (gasless CTF):** `POST {RELAYER_HOST}/submit → {transactionID, state:"STATE_NEW"}`, then poll `GET /transaction` for the on-chain hash. Needs `relayerApiKey` + `relayerApiKeyAddress`. Redeem via raw EOA against the CTF contract is **not** reliable for proxy/Safe-held positions → relayer/deposit-wallet batch is the realistic path.

---

## 9. Milestones (deliverables + gates)

- **M0 — Exchange/wallet/protocol conformance** (needs creds). Prove: wallet/signatureType signs+submits; post-only never becomes taker; cancel works; partial fill identified; user+market WS; heartbeat; response-loss/duplicate-submit handling; reconnect+snapshot resync; split/merge behavior+latency; trade-side semantics fixed by test. **Outputs latency distribution for M0.5.**
- **M0.5 — Recorder + latency-calibrated shadow markout** (read-only, parallel with M0). Per §7. Gate to continue: execution model trustworthy + observed latency/fill/adverse-selection distributions don't show the strategy is *necessarily* infeasible (NOT "raw markout must already be positive" — early samples are tiny/skewed).
- **M1 — Market registry + recorder + domain model.** Binary markets only. Domain model already understands YES+NO+complete set.
- **M2 — Execution / inventory / risk core.** Immutable fill ledger; shadow/confirmed inventory; order state machine incl. `UNKNOWN`; CTF op state machine; worst-case terminal risk; heartbeat deadman; GTD catalyst guard; stale/unsynced kill; **deterministic event replay** (same events → identical book/orders/fills/inventory/reservations — a safety requirement, not research).
- **M2.5 — Tiny live canary.** Pre-split tiny inventory; quote **two economic directions** (allocator picks 2–4 real orders), post-only, heartbeat+GTD+stale-kill+max-unmatched. Merge at threshold to validate the full capital cycle. Measure real fill prob, submit/cancel latency, 1s/5s/30s markout, complete-set recovery, reward eligibility, inventory recovery time. **Not** a naked single-leg quote (single leg = unpaired exposure, can't test recovery, and <0.10/>0.90 markets need two-sided to score).
- **M3 — Decide quoter positioning from canary data:** core-positive spread MM / subsidy-dependent reward MM / hybrid / stop. Reward quoter solves `max_s [reward_score(s) − markout_loss(s) − inventory_cost(s)]` — never mechanically parked at `max_incentive_spread`.
- **M4 — Full simulator + toxicity:** queue model, counterfactual fills, OFI/event-CVD (skew/widen/cancel only), cancel-burst, reward-aware placement, policy replay.

---

## 10. Parallel-work coordination (for syncing agents)

**Freeze these FOUR contracts before parallelizing (Contract #1 includes the #1b parsed union). Changes to any of them require editing this file + pinging others.**

- **Contract #1 — Recorded event schema** (`feeds/recorder.py`). Everything downstream (book_builder, shadow, replay) reads this; `raw_payload` is retained verbatim but **downstream must not rely on un-frozen ad hoc parsing**. Replay ordering key = `(recording_run_id, local_sequence)` — Market WS provides a `hash` but **no official monotonic sequence**, so ordering is assigned locally.
  ```
  schema_version            # bump on any field change
  recording_run_id          # one per recorder process/session
  local_sequence            # monotonic per run, assigned at ingest (THE replay order key)
  exchange_timestamp
  local_receive_timestamp
  monotonic_timestamp
  source_kind               # market_ws | user_ws | rest_snapshot | synthetic_marker
  channel
  condition_id, asset_id
  event_type
  book_hash                 # Market WS `hash` when present
  snapshot_id               # links a REST snapshot to the deltas it verifies
  ingestion_status          # OK | STALE | UNSYNCED | GAP  (UNSYNCED/GAP excluded from markout stats)
  connection_id, reconnect_marker
  parser_version
  raw_payload               # verbatim
  ```
- **Contract #1b — `ParsedRecordedEvent` typed union.** The single decode boundary — WS-A/WS-C/replay consume THIS, never re-parse `raw_payload`. One frozen `decode_recorded_event(RecordedEvent) -> ParsedRecordedEvent`; bump `parser_version` (Contract #1) when decoding changes. Field sets verified vs Market/User WS docs:
  ```
  # Market channel
  MarketBookSnapshot : asset_id, market, bids[(price,size)], asks[(price,size)], hash, timestamp
  MarketPriceChange  : market, changes[(asset_id, side, price, size, hash, best_bid, best_ask)], timestamp
                       #   NO top-level asset_id; ONE msg may carry BOTH YES & NO; size==0 ⇒ level removed;
                       #   per-change `hash` verifies/updates THAT asset's book (not a market-wide hash)
  MarketLastTrade    : asset_id, market, price, side, size, fee_rate_bps, timestamp
  TickSizeChange     : asset_id, market, old_tick_size, new_tick_size, timestamp
  BestBidAsk         : asset_id, market, best_bid, best_ask, timestamp        # custom_feature_enabled
  MarketResolved     : condition_id, ...                                       # custom_feature_enabled
  # User channel (WebSocket — live; NO bucket/tx metadata, do not assume it)
  UserOrderEvent     : order_id, asset_id, market, type(PLACEMENT|UPDATE|CANCELLATION), price, size, size_matched, status, timestamp
UserTradeWsEvent   : trade_id, taker_order_id, asset_id, market, side, outcome, price, size, status, maker_orders[WsMakerOrderFill], match_time, last_update?, timestamp
  # REST trades endpoint — carries settlement/bucket metadata (Contract #4)
RestTradeEvent     : trade_id, taker_order_id, asset_id, market, side, outcome, price, size, status, maker_orders[RestMakerOrderFill], bucket_index, transaction_hash, match_time, timestamp
WsMakerOrderFill   : order_id, matched_amount, owner, asset_id, outcome, price
RestMakerOrderFill : order_id, matched_amount, owner, maker_address, asset_id, outcome, price, fee_rate_bps, side
  # NOTE: all WS numeric fields arrive as JSON strings → the decode boundary normalizes types.
  #   Logical fill (Contract #4) is DERIVED from maker_orders[]; bucket settlement updates ONLY from a
  #   RestTradeEvent (or later status carrying bucket metadata). WS-only fills stay unconfirmed — the
  #   parser must NOT fabricate bucket_index/transaction_hash that the WS frame does not contain.
  # Recorder-internal
  RestSnapshot       : asset_id, bids[], asks[], hash, snapshot_id, server_ts
  SyntheticMarker    : kind(RECONNECT|UNSYNCED|GAP|HEARTBEAT_MISS), detail
  ```
- **Contract #2 — `ExchangePort` / `CtfPort` interfaces** (`execution/exchange_port.py`, `ctf_port.py`). Domain/strategy/risk depend only on these **typed** request/response shapes (not bare method names), so WS-D, WS-B-risk and the fake-port test double all model accepted/delayed/duplicate/timeout identically. **Timeout / lost-response MUST return an `UNKNOWN` result, never raise an exception-only** (§4.4 lifecycle).
  ```
  ExchangePort (methods):
    submit_order(SubmitOrderRequest)  -> SubmitOrderResult
    cancel_order(CancelOrderRequest)  -> CancelOrderResult     # may report fills_after_cancel
    cancel_market_orders(condition_id)-> CancelResult
    fetch_open_orders(condition_id?)  -> list[OpenOrder]
    fetch_book_snapshot(asset_id)     -> BookSnapshot
    subscribe_market_events(condition_ids) -> stream of Contract #1 events
    subscribe_user_events()                -> stream of Contract #1 events
    post_heartbeat(HeartbeatRequest)  -> HeartbeatAck    # user-global deadman; NOT per-market

  # Requests SPLIT by intent — post-only vs aggressive is a protocol fact, not a flag:
  PassivePostOnlyOrderRequest:           # the ONLY request type v1 strategy emits
    local_intent_id        # our idempotency key (no native client_order_id)
    condition_id, asset_id, side, price, size
    order_type             # GTC | GTD only  (post-only forbids FOK/FAK)
    post_only = true       # always; must never cross
    expiration             # GTD only
    tick_size, neg_risk    # snapshotted at sign time
    funder, signature_type # 0/1/2/3
    signed_payload_hash, signed_payload   # exact bytes; RESEND IDENTICAL on retry (do not re-salt)
    submit_attempt
  AggressiveOrderRequest:                # FOK/FAK/taker — NOT used by v1 strategy (M0 probes only)
    ... same identity/signing fields; order_type ∈ {FOK, FAK, GTC-taker}; post_only = false

  SubmitOrderResult:
    status                    # ACCEPTED | REJECTED | UNKNOWN
    insert_status?            # matched | live | delayed | unmatched   (verified)
    exchange_order_id?, order_hash?
    error_code?               # ORDER_DELAYED | FOK_ORDER_NOT_FILLED_ERROR | MARKET_NOT_READY | post_only_cross_reject | ...
    http_status               # 2xx | 425 | 503 | 4xx ...
    restricted_mode           # NORMAL | RESTARTING(425) | POST_ONLY | CANCEL_ONLY | DISABLED | UNKNOWN
    retry_after_seconds?      # MAY be absent (Cloudflare 429s carry none) → adapter owns exp-backoff
    raw_response
  # INVARIANT (post-only): a PassivePostOnlyOrderRequest result MUST be insert_status=`live`
  #   OR status=REJECTED(error_code=post_only_cross_reject). insert_status ∈ {matched,delayed,unmatched}
  #   on a post-only order = CONFORMANCE FAILURE → protocol breaker (halt; do NOT treat as a fill).
  # BATCH: POST /orders may return top-level success=true with per-order errors → normalize EACH order;
  #   never infer success from the top-level field. 425 → back off+retry; 503/POST_ONLY → switch flow, not retry.

  CancelOrderResult:        # REST cancel ACK ≠ cancellation effective — measure both (§7 cancel-latency)
    status                  # ACKED | NOT_FOUND | NOT_CANCELED | UNKNOWN
    canceled_ids            # response `canceled` (list)
    not_canceled            # response `not_canceled` (map order_id -> reason); {} when all succeed
    http_status, restricted_mode
    request_monotonic_ts, response_monotonic_ts
    effective_confirmed_ts? # when user-WS CANCELLATION confirms it actually left the book
    open_order_after_cancel?
    size_matched_delta_after_request, size_matched_delta_after_response   # fills_after_cancel (in-flight)

  CtfPort (methods): split / merge / redeem / fetch_balances
  CtfOpResult:
    local_op_id
    transaction_id?           # relayer returns {transactionID, state:"STATE_NEW"} → poll GET /transaction
    tx_hash?
    terminality               # PENDING | CONFIRMED | FAILED | UNKNOWN
    status_raw, error?, raw_response

  HeartbeatRequest:  previous_heartbeat_id   # "" on first call; else last HeartbeatAck.heartbeat_id (chained)
  HeartbeatAck:      heartbeat_id, corrected_from_400?   # broken/expired chain → 400 returns the correct id
  # Heartbeat = USER-GLOBAL deadman (cancels ALL open orders on ~10s+5s gap), NOT per-market, and a SEPARATE
  #   liveness channel from market/user-WS PING/PONG (§6). Verify exact cadence in M0.
  ```
- **Contract #3 — Inventory balance basis** (see §4.2): the `shadow_owned_total` vs `available_to_order` split. Frozen here because risk (WS-B), accounting (WS-C) and quoter all consume it.
- **Contract #4 — Settlement identity** (see §3.2): logical-fill key `(trade_id, order_id)` vs settlement-bucket key `(trade_id, bucket_index, transaction_hash?)`, reconciled by `match_time`; status tagged logical-trade vs bucket. Frozen because the fill ledger (WS-B), reconciler (WS-D) and accounting (WS-C) all key off it.

**Independent workstreams once frozen:**
- **WS-A (no creds):** `feeds/` — recorder, book_builder, market_ws, user_ws read path. Depends on Contract #1.
- **WS-B (no creds, pure):** `domain/` — inventory ledger, order model, market_spec, routing, risk. Unit-tested in isolation. Depends on nothing external.
- **WS-C (no creds):** `accounting/markout.py` + shadow engine in `app/recorder_main.py`. Depends on Contract #1 + WS-B reference-price calc.
- **WS-D (creds, gated):** `execution/` adapters + `app/conformance_main.py`. Depends on Contract #2. **Blocked on credentials (§12).**

Suggested ownership: one agent per workstream. WS-A/B/C can all start now. WS-D waits for the user's credentials and explicit authorization.

---

## 11. Open decisions

- **Edge positioning:** UNDECIDED until M2.5. Default stance = defensive reward-aware; classify per market. Do not pre-commit.
- **Protocol stack freeze (OPEN — must resolve before M0; supersedes the old "start on `py-clob-client`" note).** CLOB V2 is live and **v1 is unsupported** (§8), so v1 is off the table. Decide before M0: (a) **client** — `py-sdk` (beta) / `py-clob-client-v2` / `ts-sdk` / `rs-clob-client-v2` / direct REST; **none is a known-good type-3 path** (§8 — #70 affects Python, TS *and* Rust), so each must pass the M0 `create/derive key → sign → postOrder → cancel → user WS` probe before selection; (b) **wallet/signing** — type-3 deposit-wallet (no working SDK today) vs falling back to an existing **type-1/2 proxy/Safe** account for the canary (the only confirmed-working paths); (c) **CTF execution** — direct on-chain vs relayer (gasless). All three sit behind `ExchangePort`/`CtfPort` (Contract #2) so the choice doesn't leak into domain/strategy. The M0 conformance harness exists precisely to make this decision empirically.
- **REST-trade `source_kind` interpretation (recorded, not a contract change).** Contract #1's `source_kind` enum stays frozen at `market_ws | user_ws | rest_snapshot | synthetic_marker`. The REST trades endpoint (`RestTradeEvent`, Contract #1b/#4) is recorded as `source_kind=rest_snapshot` + `event_type='trade'`; `decode_recorded_event` distinguishes it from a WS trade by `(source_kind, event_type)`. If a dedicated `rest_trades` source_kind is later wanted, that is a Contract #1 change (bump `schema_version`) — flagging here first per process.
- **`price_change` delta array field (M0-verify, defensively handled).** Live market WS `price_change` frames carry the delta array under `price_changes`; `decode_recorded_event` reads `price_changes` with `changes` as a fallback (mirrors the `bids/asks`↔`buys/sells` fallback in `_book_sides`). Confirm the exact field on our socket in M0 and drop the fallback once frozen. Not a contract change — the parsed `MarketPriceChange` shape is unchanged.
- **Settlement-status wire form (M0-verify, defensively handled).** The REST `/data/trades` endpoint reports protobuf-style status names (`TRADE_STATUS_CONFIRMED`), while the User WS uses the bare form (`CONFIRMED`). `_parse_settlement_status` strips a leading `TRADE_STATUS_` prefix so both decode to the same frozen `SettlementStatus`. Without this, REST rows raise `DecodeError` → no `SettlementBucket` → WS fills never reconcile terminal (they'd stay in `unconfirmed_fill_cap` forever). Confirm the exact form per channel in M0. Not a contract change — the `SettlementStatus` enum is unchanged.
- (Add proposals here rather than diverging in code.)

**Applied in review #1 (2026-06-30), verified vs official CLOB V2 docs — now frozen, not open:**
- Settlement status set incl. non-terminal `RETRYING` → §3.2.
- Inventory balance basis (`shadow_owned_total` vs `available_to_order`) → §4.2 / Contract #3.
- Contract #1 replay metadata (`local_sequence`, `source_kind`, `book_hash`, `ingestion_status`, versions) → §10.
- Contract #2 typed request/response incl. `insert_status`, `UNKNOWN`-on-timeout, signed-payload idempotency → §10.
- V2 facts + SDK bug #70 + relayer flow → §8; env/config → §12.

**Applied in review #2 (2026-06-30), verified vs official docs / GitHub issues:**
- Corrected the Rust claim: **no SDK has a working type-3 path** (#70 repros on `rs-clob-client-v2` too) → §8 + protocol-stack decision above.
- Contract #2 **post-only request split** (`PassivePostOnlyOrderRequest` = the only type v1 emits; `AggressiveOrderRequest` M0-only) + post-only result invariant + protocol breaker → §10.
- Contract #2 **heartbeat-id chain** (`previous_heartbeat_id`; user-global; separate from WS PING/PONG) → §10 + §6.
- Contract #2 **matching-engine restricted modes** (`http_status`, `restricted_mode`, optional `retry_after_seconds`, per-order batch normalization) → §10.
- Contract count corrected **TWO → THREE** → §10.

**Applied in review #3 (2026-06-30), verified vs official docs:**
- **Contract #1b** `ParsedRecordedEvent` typed union + single `decode_recorded_event` boundary (Market/User WS field sets) → §10. Stops WS-A/WS-C re-parsing raw payloads.
- **Contract #2** `CancelOrderResult` frozen (`canceled`/`not_canceled`, ACK-vs-effective timestamps, `fills_after_cancel` deltas) → §10.
- **Contract #4** settlement identity: logical-fill vs `bucket_index`/`match_time` settlement-bucket key; no early promote across buckets → §3.2 / §10.
- Contract count **THREE → FOUR** (Contract #1 now includes #1b).

**Applied in review #4 (2026-06-30), verified vs official Market/User WS docs:**
- Fixed `MarketPriceChange`: per-change `asset_id`+`hash` (no top-level asset_id; one message may carry both YES & NO; values are JSON strings) → §10 Contract #1b. Restores per-asset book-hash verification.
- Split `UserTradeWsEvent` (WS, no bucket/tx) vs `RestTradeEvent` (REST, with `bucket_index`/`transaction_hash`/`match_time`); split `WsMakerOrderFill` vs `RestMakerOrderFill`; preserve WS `match_time`/`last_update` for later REST reconciliation; WS-only fills stay unconfirmed until bucket metadata arrives → §10 Contract #1b + Contract #4.

---

## 12. Credentials & config needed from the user

**Nothing is needed to start WS-A / WS-B / WS-C (M0.5 read-only).**

For **M0 / M2.5 (live, gated)** — see chat for the actionable request and security notes. Env var names (extend `config` / new `mm_v2` settings):
```
POLY_PRIVATE_KEY            # owner/signer key — dedicated low-value wallet; NEVER commit / paste in chat
POLY_FUNDER_ADDRESS         # collateral holder: deposit wallet (type 3) / proxy / Safe / EOA
POLY_SIGNATURE_TYPE         # 0 EOA / 1 email-proxy / 2 browser-wallet-proxy / 3 POLY_1271 deposit-wallet (new API users)
POLY_API_KEY/SECRET/PASSPHRASE   # L2 CLOB creds; derive via create_or_derive_api_key in M0
POLY_HOST=https://clob.polymarket.com
# Relayer (gasless CTF) — only if CTF goes via relayer (see §11 protocol-stack decision):
RELAYER_API_KEY
RELAYER_API_KEY_ADDRESS
RELAYER_HOST=https://relayer-v2.polymarket.com
# Funding: small pUSD on Polygon (CLOB V2 replaced USDC.e). Gas: none if relayer (gasless);
#   POL/MATIC only for direct on-chain split/merge/redeem. Trading allowances enabled.
# NOTE: requirements.txt pins v1 py-clob-client (>=0.18) — must migrate to the §11-chosen v2 stack before M0.
```

---
