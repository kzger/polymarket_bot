"""Market WebSocket read path (WS-A).

Subscribes to the public Market channel (L2 snapshot, price_change, best
bid/ask, tick-size change, last_trade_price) and hands raw frames to the
recorder (Contract #1). No credentials required. Implementation deferred to the
M0.5 recorder build; the decode boundary is :mod:`mm_v2.feeds.events`.
"""

__all__: list[str] = []
