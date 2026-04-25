"""ebay_data_fetcher の単体テスト（API はモック）。"""

from __future__ import annotations

from reports.ebay_data_fetcher import SoldLine, parse_get_orders_response


def _sample_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<GetOrdersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <HasMoreOrders>false</HasMoreOrders>
  <OrderArray>
    <Order>
      <OrderID>98765</OrderID>
      <OrderStatus>Completed</OrderStatus>
      <CheckoutStatus><Status>Complete</Status></CheckoutStatus>
      <TransactionArray>
        <Transaction>
          <Item>
            <ItemID>111222333</ItemID>
            <Title>One Piece Card Japanese PSA10</Title>
            <SKU>m999</SKU>
          </Item>
          <TransactionPrice currencyID="USD">123.45</TransactionPrice>
        </Transaction>
      </TransactionArray>
    </Order>
  </OrderArray>
</GetOrdersResponse>"""


def test_parse_get_orders_response_extracts_sold_line() -> None:
    rows, has_more = parse_get_orders_response(_sample_xml())
    assert has_more is False
    assert len(rows) == 1
    r = rows[0]
    assert r.order_id == "98765"
    assert r.item_id == "111222333"
    assert "One Piece" in r.title
    assert r.price_usd == 123.45
    assert r.sku == "m999"


def test_parse_skips_non_completed_order() -> None:
    xml = """<?xml version="1.0" encoding="utf-8"?>
<GetOrdersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <OrderArray>
    <Order>
      <OrderID>1</OrderID>
      <OrderStatus>Active</OrderStatus>
      <TransactionArray/>
    </Order>
  </OrderArray>
</GetOrdersResponse>"""
    rows, _ = parse_get_orders_response(xml)
    assert rows == []


def test_parse_ack_failure_returns_empty() -> None:
    xml = """<?xml version="1.0" encoding="utf-8"?>
<GetOrdersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Failure</Ack>
</GetOrdersResponse>"""
    rows, has_more = parse_get_orders_response(xml)
    assert rows == [] and has_more is False


def test_sold_line_dataclass() -> None:
    s = SoldLine("o", "i", "t", 1.5, "sku")
    assert s.price_usd == 1.5
