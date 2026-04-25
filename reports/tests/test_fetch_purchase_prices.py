"""fetch_purchase_prices の単体テスト（Sheets / Playwright はモック）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from reports.fetch_purchase_prices import (
    PURCHASE_HEADER,
    ConsecutiveErrorTracker,
    MercariAccessLock,
    col_index_to_a1,
    compute_new_purchase_column_index,
    find_purchase_column_index,
    run,
)


def test_col_index_to_a1() -> None:
    assert col_index_to_a1(0) == "A"
    assert col_index_to_a1(7) == "H"
    assert col_index_to_a1(25) == "Z"
    assert col_index_to_a1(26) == "AA"


def test_find_purchase_column_index() -> None:
    row = ["ItemID", "x", "y", "url", "", "", "", "仕入価格(JPY)"]
    assert find_purchase_column_index(row) == 7
    assert find_purchase_column_index(["仕入価格（JPY）"]) == 0
    assert find_purchase_column_index(["a", "b"]) is None


def test_compute_new_purchase_column_index() -> None:
    short = ["A", "B", "C", "D", "E", "F", "G"]
    assert compute_new_purchase_column_index(short) == 7
    wide = ["A", "B", "C", "D", "E", "F", "G", "extra", ""]
    assert compute_new_purchase_column_index(wide) == 8


def test_consecutive_error_tracker() -> None:
    t = ConsecutiveErrorTracker()
    for _ in range(4):
        assert t.on_failure() is False
    assert t.on_failure() is True
    assert t.count == 5
    assert not t.should_abort()
    for _ in range(4):
        assert t.on_failure() is False
    assert t.count == 9
    assert not t.should_abort()
    assert t.on_failure() is False
    assert t.should_abort()
    t.on_success()
    assert t.count == 0


def test_meta_and_data_testid_price_from_html() -> None:
    """Playwright 無しで、想定 HTML から価格相当値を読めること（セレクタの目安）。"""
    html = """
    <html><head>
      <meta property="product:price:amount" content="3500"/>
    </head><body>
      <div data-testid="price">¥3,500</div>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.select_one('meta[property="product:price:amount"]')
    assert meta is not None
    assert int(meta["content"]) == 3500
    div = soup.select_one('[data-testid="price"]')
    assert div is not None
    digits = "".join(c for c in div.get_text() if c.isdigit())
    assert int(digits) == 3500


@patch("reports.fetch_purchase_prices.update_cell")
@patch("reports.fetch_purchase_prices.read_data_rows")
@patch("reports.fetch_purchase_prices.read_header_row")
def test_run_dry_run_passes_dry_run_to_update_cell(
    mock_header: MagicMock,
    mock_rows: MagicMock,
    mock_update_cell: MagicMock,
) -> None:
    """dry-run では update_cell が常に dry_run=True（Sheets 実書き込みなし）。"""
    mock_svc = MagicMock()
    mock_header.return_value = ["ItemID", "名", "先", "url", "e", "f", "g", "仕入価格(JPY)"]
    mock_rows.return_value = [
        ["366126547071", "", "", "https://jp.mercari.com/item/m36749006311", "", "", "", ""],
    ]

    def fetch_impl(_url: str) -> tuple[int | None, str | None]:
        return 3500, None

    run(
        dry_run=True,
        limit=10,
        fetch_impl=fetch_impl,
        sleep_fn=lambda _x: None,
        get_service=lambda: mock_svc,
        spreadsheet_id="test_spreadsheet_id_no_config",
    )

    assert mock_update_cell.called
    for c in mock_update_cell.call_args_list:
        assert c.kwargs.get("dry_run") is True


@patch("reports.fetch_purchase_prices.update_cell")
@patch("reports.fetch_purchase_prices.read_data_rows")
@patch("reports.fetch_purchase_prices.read_header_row")
def test_run_adds_header_when_missing(
    mock_header: MagicMock,
    mock_rows: MagicMock,
    mock_update_cell: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_header.return_value = ["ItemID", "名", "先", "url", "e", "f", "g"]
    mock_rows.return_value = []
    run(
        dry_run=False,
        limit=1,
        fetch_impl=lambda u: (100, None),
        sleep_fn=lambda _x: None,
        get_service=lambda: mock_svc,
        spreadsheet_id="test_spreadsheet_id_no_config",
    )
    mock_update_cell.assert_called()
    first = mock_update_cell.call_args_list[0]
    args, kwargs = first[0], first[1]
    assert args[3] == 1
    assert args[5] == PURCHASE_HEADER
    assert kwargs.get("dry_run") is False


def test_mercari_access_lock_ignore() -> None:
    with MercariAccessLock(path="/tmp/mercari_access_lock_test_ignore", ignore=True):
        pass
