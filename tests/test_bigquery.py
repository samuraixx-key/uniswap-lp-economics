from datetime import date

import pytest

from uniswap_lp_economics.config import POOL_ADDRESS
from uniswap_lp_economics.data.bigquery import build_pool_logs_query, month_windows


def test_query_filters_both_tables_by_partition_and_pool() -> None:
    q = build_pool_logs_query(date(2026, 7, 1), date(2026, 8, 1))
    # Partition filters on both tables keep the scan (and cost) bounded.
    assert q.count("block_timestamp >= TIMESTAMP('2026-07-01')") == 2
    assert q.count("block_timestamp < TIMESTAMP('2026-08-01')") == 2
    assert f"address = '{POOL_ADDRESS}'" in q
    assert "from_address" in q and "to_address" in q


def test_month_windows_split_on_calendar_months() -> None:
    assert month_windows(date(2026, 7, 1), date(2026, 10, 1)) == [
        (date(2026, 7, 1), date(2026, 8, 1)),
        (date(2026, 8, 1), date(2026, 9, 1)),
        (date(2026, 9, 1), date(2026, 10, 1)),
    ]


def test_month_windows_handle_partial_months() -> None:
    assert month_windows(date(2026, 12, 15), date(2027, 1, 10)) == [
        (date(2026, 12, 15), date(2027, 1, 1)),
        (date(2027, 1, 1), date(2027, 1, 10)),
    ]


@pytest.mark.live
def test_live_bigquery_dry_run() -> None:
    from uniswap_lp_economics.data.bigquery import fetch_pool_logs

    assert fetch_pool_logs(date(2026, 9, 1), date(2026, 9, 2), dry_run=True) is None
