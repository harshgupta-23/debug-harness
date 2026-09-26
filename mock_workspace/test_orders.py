"""Targeted unit tests for order calculation."""

from routes import compute_total, get_order_details


def test_compute_total_standard():
    assert compute_total(100.0, 0.20) == 80.0


def test_compute_total_null_discount():
    assert compute_total(100.0, None) == 100.0


def test_get_order_details():
    res = get_order_details(1)
    assert res["order_id"] == 1
    assert res["final_total"] == 85.0
