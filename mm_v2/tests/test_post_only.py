"""Contract #2 post-only invariant tests.

Request side: a ``PassivePostOnlyOrderRequest`` must be GTC/GTD, post_only, with
a tick-aligned price in (0, 1) and a positive size; GTD requires an expiration.

Result side (the protocol breaker): a post-only result must be
``insert_status='live'`` OR ``REJECTED(post_only_cross_reject)``. Any of
``matched / delayed / unmatched`` is a conformance failure that must halt — it
must NOT be treated as a fill (PLAN §10 Contract #2).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from mm_v2.domain.order import OrderType, Side
from mm_v2.execution.exchange_port import (
    ERR_MARKET_NOT_READY,
    ERR_POST_ONLY_CROSS_REJECT,
    InsertStatus,
    PassivePostOnlyOrderRequest,
    PostOnlyConformanceError,
    PostOnlyOutcome,
    RestrictedMode,
    SubmitOrderResult,
    SubmitStatus,
    assert_post_only_conformance,
    classify_post_only_result,
    post_only_request_violations,
)


def make_request(**overrides) -> PassivePostOnlyOrderRequest:
    base = dict(
        local_intent_id="intent-1",
        condition_id="0xcond",
        asset_id="yes-token",
        side=Side.BUY,
        price=Decimal("0.52"),
        size=Decimal("100"),
        order_type=OrderType.GTC,
        tick_size=Decimal("0.01"),
    )
    base.update(overrides)
    return PassivePostOnlyOrderRequest(**base)


def make_result(**overrides) -> SubmitOrderResult:
    base = dict(status=SubmitStatus.ACCEPTED, http_status=200)
    base.update(overrides)
    return SubmitOrderResult(**base)


# --- request invariants -----------------------------------------------------
def test_valid_gtc_request_has_no_violations() -> None:
    assert post_only_request_violations(make_request()) == []


def test_valid_gtd_request_with_expiration_has_no_violations() -> None:
    req = make_request(order_type=OrderType.GTD, expiration=1700000000)
    assert post_only_request_violations(req) == []


def test_gtd_without_expiration_is_violation() -> None:
    req = make_request(order_type=OrderType.GTD, expiration=None)
    violations = post_only_request_violations(req)
    assert any("expiration" in v.lower() for v in violations)


def test_gtc_with_expiration_is_violation() -> None:
    req = make_request(order_type=OrderType.GTC, expiration=1700000000)
    assert any("expiration" in v.lower() for v in post_only_request_violations(req))


def test_fok_order_type_is_violation() -> None:
    req = make_request(order_type=OrderType.FOK)
    assert any("order_type" in v.lower() or "fok" in v.lower() for v in post_only_request_violations(req))


def test_post_only_false_is_violation() -> None:
    req = make_request(post_only=False)
    assert any("post_only" in v.lower() for v in post_only_request_violations(req))


@pytest.mark.parametrize("bad_price", [Decimal("0"), Decimal("1"), Decimal("-0.1"), Decimal("1.5")])
def test_price_out_of_open_interval_is_violation(bad_price: Decimal) -> None:
    req = make_request(price=bad_price)
    assert any("price" in v.lower() for v in post_only_request_violations(req))


def test_price_not_tick_aligned_is_violation() -> None:
    req = make_request(price=Decimal("0.525"), tick_size=Decimal("0.01"))
    assert any("tick" in v.lower() for v in post_only_request_violations(req))


def test_non_positive_size_is_violation() -> None:
    req = make_request(size=Decimal("0"))
    assert any("size" in v.lower() for v in post_only_request_violations(req))


# --- result conformance (the protocol breaker) ------------------------------
def test_result_live_is_rested() -> None:
    result = make_result(insert_status=InsertStatus.LIVE, exchange_order_id="ord-1")
    assert classify_post_only_result(result) is PostOnlyOutcome.RESTED
    assert assert_post_only_conformance(result) is PostOnlyOutcome.RESTED


def test_result_rejected_cross_is_ok() -> None:
    result = make_result(
        status=SubmitStatus.REJECTED,
        http_status=400,
        error_code=ERR_POST_ONLY_CROSS_REJECT,
    )
    assert classify_post_only_result(result) is PostOnlyOutcome.REJECTED_CROSS
    assert assert_post_only_conformance(result) is PostOnlyOutcome.REJECTED_CROSS


@pytest.mark.parametrize(
    "insert_status",
    [InsertStatus.MATCHED, InsertStatus.DELAYED, InsertStatus.UNMATCHED],
)
def test_result_non_live_insert_is_conformance_failure(insert_status: InsertStatus) -> None:
    result = make_result(insert_status=insert_status)
    assert classify_post_only_result(result) is PostOnlyOutcome.CONFORMANCE_FAILURE
    with pytest.raises(PostOnlyConformanceError):
        assert_post_only_conformance(result)


def test_result_unknown_is_unknown() -> None:
    result = make_result(status=SubmitStatus.UNKNOWN, http_status=0)
    assert classify_post_only_result(result) is PostOnlyOutcome.UNKNOWN
    # UNKNOWN must not raise — it is reconciled, not a breaker.
    assert assert_post_only_conformance(result) is PostOnlyOutcome.UNKNOWN


def test_result_rejected_other_reason_is_not_a_breaker() -> None:
    result = make_result(
        status=SubmitStatus.REJECTED,
        http_status=503,
        error_code=ERR_MARKET_NOT_READY,
        restricted_mode=RestrictedMode.POST_ONLY,
    )
    assert classify_post_only_result(result) is PostOnlyOutcome.REJECTED_OTHER
    # A rejection for an allowed reason (market not ready) is not a conformance failure.
    assert assert_post_only_conformance(result) is PostOnlyOutcome.REJECTED_OTHER
