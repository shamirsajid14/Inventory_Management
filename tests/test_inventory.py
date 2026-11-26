import csv
from io import StringIO
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.errors import CheckViolation
import pytest

from admin_app import app
import main
import models


def product(name, quantity, unit, minimum="0", price="120"):
    return models.add_product(name, price, quantity, minimum, "Test groceries", unit)


def sale_rows(test_database):
    with test_database() as connection:
        return connection.execute(
            "SELECT quantity, unit_price, quantity * unit_price FROM sales ORDER BY id"
        ).fetchall()


def test_fractional_restock_and_remove():
    apples = product("Test apples", "1", "kg")
    assert models.add_stock(apples.id, "0.250", note="Delivery").quantity == Decimal("1.250")
    assert models.remove_stock(apples.id, "0.250", note="Damaged").quantity == Decimal("1")
    entries = models.get_stock_history(apples.id)
    assert [entry[1:] for entry in entries] == [
        ("removal", Decimal("-0.25"), "kg", "Damaged", Decimal("1")),
        ("restock", Decimal("0.25"), "kg", "Delivery", Decimal("1.25")),
    ]
    assert all(entry[0] for entry in entries)
    with pytest.raises(models.InventoryError, match="stock history"):
        models.delete_product(apples.id)


def test_reject_half_piece_and_insufficient_stock(test_database):
    jars = product("Test jars", "2", "piece")
    for operation in (models.add_stock, models.remove_stock, models.record_sale):
        with pytest.raises(models.InventoryError, match="whole number"):
            operation(jars.id, "0.5")
    for operation in (models.remove_stock, models.record_sale):
        with pytest.raises(models.InventoryError, match="Only 2 pieces"):
            operation(jars.id, "3")
    assert models.get_product(jars.id).quantity == Decimal(2)
    assert sale_rows(test_database) == []
    assert models.get_stock_history(jars.id) == []


def test_half_dozen_sale_and_retry(test_database):
    oranges = product("Test oranges", "5", "dozen")
    token = uuid4()
    sale = models.record_sale(oranges.id, "0.5", token)
    assert sale.total == Decimal(60)
    assert models.record_sale(oranges.id, "0.5", token).replayed
    assert models.get_product(oranges.id).quantity == Decimal("4.5")
    assert sale_rows(test_database) == [(Decimal("0.5"), Decimal(120), Decimal(60))]
    assert [row[1:] for row in models.get_stock_history(oranges.id)] == [
        ("sale", Decimal("-0.5"), "dozen", None, Decimal("4.5")),
    ]
    with test_database() as connection:
        assert connection.execute(
            "SELECT count(*) FROM stock_movements m JOIN sales s ON s.id = m.sale_id"
        ).fetchone() == (1,)


def test_failed_movement_insert_rolls_back_stock_and_sale(test_database):
    oranges = product("Test oranges", "5", "dozen")
    with test_database() as connection:
        connection.execute(
            "ALTER TABLE stock_movements ADD CONSTRAINT test_fail_movement CHECK (kind <> 'sale')"
        )
    try:
        with pytest.raises(CheckViolation, match="test_fail_movement"):
            models.record_sale(oranges.id, "0.5", uuid4())
        assert models.get_product(oranges.id).quantity == Decimal(5)
        assert sale_rows(test_database) == []
        assert models.get_stock_history(oranges.id) == []
    finally:
        with test_database() as connection:
            connection.execute("ALTER TABLE stock_movements DROP CONSTRAINT test_fail_movement")


def test_queue_restock_and_history_view():
    apples = product("Test apples", "4", "kg", minimum="7")
    with TestClient(app) as client:
        queue = client.get("/admin/products?low=1")
        assert "Restock queue" in queue.text and "3 kg" in queue.text and apples.name in queue.text
        path = f"/admin/products?low=1&action=restock&id={apples.id}"
        form = client.get(path)
        assert 'value="3.000"' in form.text
        refreshed = client.post(path, data={"amount": "3", "note": "Queue delivery"})
        assert refreshed.status_code == 200 and "No products match" in refreshed.text
        assert client.get("/api/products").json()["Products"][0]["quantity"] == 7
        history = client.get(f"/admin/products?action=history&id={apples.id}")
        assert "+3 kg" in history.text and "7 kg" in history.text and "Queue delivery" in history.text


def test_cli_quantity_edit_records_a_correction(monkeypatch, capsys):
    apples = product("Test apples", "4", "kg")
    answers = iter(["3", str(apples.id), "Test apples", "120", "3.75", "0", "Test groceries",
                    "h", str(apples.id), "8"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    main.main()
    assert "Correction | −0.25 kg | Balance 3.75 kg" in capsys.readouterr().out
    assert models.get_stock_history(apples.id)[0][1:3] == ("correction", Decimal("-0.25"))


def test_report_and_csv_share_pakistan_date_boundaries(test_database):
    oranges = product("Test oranges", "5", "dozen", price="999")
    apples = product("Test apples", "5", "kg")
    with test_database() as connection:
        connection.execute(
            """
            INSERT INTO sales (product_id, quantity, unit_price, sold_at) VALUES
            (%s, 3, 120, '2025-01-09 18:59:59+00'),
            (%s, 0.5, 120, '2025-01-09 19:00:00+00'),
            (%s, 0.25, 100, '2025-01-10 18:59:59+00'),
            (%s, 2, 120, '2025-01-10 19:00:00+00')
            """,
            (oranges.id, oranges.id, apples.id, oranges.id),
        )
    filters = {"start": "2025-01-10", "end": "2025-01-10"}
    with TestClient(app) as client:
        page = client.get("/admin/sales/reports", params=filters)
        assert page.status_code == 200
        assert "Rs 85.00" in page.text and "Rs 60.00" in page.text and "Rs 25.00" in page.text
        assert "0.25 kg" in page.text and "0.5 dozen" in page.text
        assert "start=2025-01-10&amp;end=2025-01-10" in page.text
        export = client.get("/admin/sales/reports.csv", params=filters)
        assert export.status_code == 200 and "attachment" in export.headers["Content-Disposition"]
        daily, total = csv.DictReader(StringIO(export.content.decode("utf-8-sig")))
        assert daily["Date (Pakistan time)"] == "2025-01-10"
        assert daily["Sales"] == "2" and daily["Known revenue (PKR)"] == "85.00"
        assert Decimal(daily["Kg sold"]) == Decimal("0.25")
        assert Decimal(daily["Dozen sold"]) == Decimal("0.5")
        assert Decimal(daily["Pieces sold"]) == 0
        assert total["Known revenue (PKR)"] == daily["Known revenue (PKR)"]
        invalid = {"start": filters["end"], "end": "2025-01-09"}
        for route in ("/admin/sales/reports", "/admin/sales/reports.csv"):
            assert client.get(route, params=invalid).status_code == 422


def test_report_explains_missing_legacy_price(test_database):
    apples = product("Legacy apples", "5", "kg")
    with test_database() as connection:
        connection.execute("ALTER TABLE sales ALTER COLUMN unit_price DROP NOT NULL")
    try:
        with test_database() as connection:
            connection.execute(
                "INSERT INTO sales (product_id, quantity, sold_at) VALUES (%s, 1, '2025-01-10 12:00+00')",
                (apples.id,),
            )
        with TestClient(app) as client:
            filters = {"start": "2025-01-10", "end": "2025-01-10"}
            assert "lack a recorded price" in client.get("/admin/sales/reports", params=filters).text
            export = client.get("/admin/sales/reports.csv", params=filters)
            row = next(csv.DictReader(StringIO(export.content.decode("utf-8-sig"))))
            assert row["Sales without price"] == "1" and row["Known revenue (PKR)"] == "0.00"
    finally:
        with test_database() as connection:
            connection.execute("DELETE FROM sales WHERE unit_price IS NULL")
            connection.execute("ALTER TABLE sales ALTER COLUMN unit_price SET NOT NULL")
