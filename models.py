from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from psycopg.errors import ForeignKeyViolation, RestrictViolation, UniqueViolation

from database import connect_db


UNIT_STEPS = {"kg": Decimal("0.001"), "dozen": Decimal("0.5"), "piece": Decimal("1")}
MAX_PRICE = Decimal("99999999.99")
MAX_QUANTITY = Decimal("9999999999.999")
PRODUCT_COLUMNS = """
    id, name, price, COALESCE(quantity, 0), COALESCE(min_stock, 0),
    category, COALESCE(unit, 'piece')
"""
SORTS = {
    "name": "lower(name), id",
    "id": "id ASC",
    "newest": "id DESC",
    "price-high": "price DESC, id",
    "price-low": "price ASC, id",
    "stock-low": "COALESCE(quantity, 0) ASC, id",
}


class InventoryError(ValueError):
    def __init__(self, message, field=None, status=422):
        super().__init__(message)
        self.field = field
        self.status = status


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    price: Decimal
    quantity: Decimal
    min_stock: Decimal
    category: str | None
    unit: str

    @property
    def low_stock(self):
        return self.quantity < self.min_stock

    @property
    def restock_amount(self):
        return max(Decimal(0), self.min_stock - self.quantity)


@dataclass(frozen=True)
class SaleResult:
    product: Product
    quantity: Decimal
    unit_price: Decimal
    replayed: bool = False

    @property
    def total(self):
        return self.quantity * self.unit_price


@dataclass(frozen=True)
class SaleEntry:
    id: int
    product_id: int
    name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    sold_at: datetime

    @property
    def total(self):
        return self.quantity * self.unit_price


@dataclass(frozen=True)
class Page:
    items: list
    total: int
    number: int
    pages: int


def decimal_value(value, label, field, limit, step, unit_error, *, positive=False):
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number < 0 or (positive and number == 0):
            raise InvalidOperation
    except InvalidOperation:
        requirement = "greater than zero" if positive else "zero or greater"
        raise InventoryError(f"{label} must be a number {requirement}.", field) from None

    if number > limit:
        raise InventoryError(f"{label} must be {limit:,} or less.", field)
    try:
        if number % step == 0:
            return number.quantize(Decimal(1).scaleb(step.as_tuple().exponent))
    except InvalidOperation:
        pass
    raise InventoryError(unit_error, field)


def stock_amount(value, unit, field="amount", *, positive=False):
    labels = {"amount": "Amount", "quantity": "Quantity", "min_stock": "Minimum stock"}
    rules = {
        "kg": "Kilograms allow up to three decimal places.",
        "dozen": "Enter whole or half dozens.",
        "piece": "Enter a whole number of pieces.",
    }
    return decimal_value(
        value, labels[field], field, MAX_QUANTITY, UNIT_STEPS[unit],
        rules[unit], positive=positive,
    )


def clean_category_name(value, *, required=False):
    name = (value or "").strip()
    if required and not name:
        raise InventoryError("Enter a category name.", "category")
    if len(name) > 100 or "\x00" in name:
        raise InventoryError("Enter a valid category name of up to 100 characters.", "category")
    return name


def validate_product(name, price, quantity, min_stock, category, unit):
    name = name.strip()
    if not name or len(name) > 100:
        raise InventoryError("Enter a product name of 1 to 100 characters.", "name")
    category = clean_category_name(category)
    if unit not in UNIT_STEPS:
        raise InventoryError("Choose kg, dozen, or piece.", "unit")
    price = decimal_value(
        price, "Price", "price", MAX_PRICE, Decimal("0.01"), "Price allows up to two decimal places.",
    )
    if quantity is not None:
        quantity = stock_amount(quantity, unit, "quantity")
    minimum = stock_amount(min_stock, unit, "min_stock")
    return name, price, quantity, minimum, category


def _product_or_error(row):
    if row is None:
        raise InventoryError("Product not found.", status=404)
    return Product(*row)


def _read_product(cursor, product_id, *, lock=False):
    lock_clause = " FOR UPDATE" if lock else ""
    cursor.execute(f"SELECT {PRODUCT_COLUMNS} FROM products WHERE id = %s{lock_clause}", (product_id,))
    return _product_or_error(cursor.fetchone())


def get_product(product_id):
    with connect_db() as connection, connection.cursor() as cursor:
        return _read_product(cursor, product_id)


def add_product(name, price, quantity, min_stock, category, unit="piece"):
    values = validate_product(name, price, quantity, min_stock, category, unit)
    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO products (name, price, quantity, min_stock, category, unit)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {PRODUCT_COLUMNS}
            """,
            (*values, unit),
        )
        return _product_or_error(cursor.fetchone())


def update_product(name, price, quantity, min_stock, category, product_id):
    with connect_db() as connection, connection.cursor() as cursor:
        product = _read_product(cursor, product_id, lock=True)
        values = validate_product(name, price, quantity, min_stock, category, product.unit)
        cursor.execute(
            f"""
            UPDATE products
            SET name = %s, price = %s, quantity = COALESCE(%s, quantity),
                min_stock = %s, category = %s
            WHERE id = %s
            RETURNING {PRODUCT_COLUMNS}
            """,
            (*values, product_id),
        )
        updated = _product_or_error(cursor.fetchone())
        if updated.quantity != product.quantity:
            _record_movement(
                cursor, updated, "correction", updated.quantity - product.quantity,
                note="Quantity changed during product edit."
            )
        return updated


def delete_product(product_id):
    try:
        with connect_db() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM products WHERE id = %s RETURNING {PRODUCT_COLUMNS}", (product_id,)
            )
            return _product_or_error(cursor.fetchone())
    except (ForeignKeyViolation, RestrictViolation) as error:
        history = "stock history" if error.diag.constraint_name == "stock_movements_product_id_fkey" else "recorded sales"
        raise InventoryError(f"This product has {history} and cannot be deleted.", status=409) from None


def _record_movement(cursor, product, kind, change, *, note=None, sale_id=None):
    cursor.execute(
        """
        INSERT INTO stock_movements (product_id, kind, quantity_change, unit, note, balance, sale_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (product.id, kind, change, product.unit, note, product.quantity, sale_id),
    )


def get_stock_history(product_id):
    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT occurred_at AT TIME ZONE 'Asia/Karachi', kind, quantity_change, unit, note, balance
            FROM stock_movements WHERE product_id = %s ORDER BY occurred_at DESC, id DESC
            """,
            (product_id,),
        )
        return cursor.fetchall()


def _update_quantity(cursor, product, amount, *, subtract):
    if subtract and amount > product.quantity:
        raise InventoryError(
            f"Only {quantity_label(product.quantity, product.unit)} are available.",
            "amount", 409,
        )
    quantity = product.quantity - amount if subtract else product.quantity + amount
    if quantity > MAX_QUANTITY:
        raise InventoryError("This amount exceeds the maximum stock quantity.", "amount")
    cursor.execute(
        f"UPDATE products SET quantity = %s WHERE id = %s RETURNING {PRODUCT_COLUMNS}",
        (quantity, product.id),
    )
    return _product_or_error(cursor.fetchone())


def _change_stock(product_id, amount, *, subtract, note):
    note = (note or "").strip()
    if len(note) > 250 or "\x00" in note:
        raise InventoryError("Enter a valid note of up to 250 characters.", "note")
    with connect_db() as connection, connection.cursor() as cursor:
        product = _read_product(cursor, product_id, lock=True)
        amount = stock_amount(amount, product.unit, positive=True)
        updated = _update_quantity(cursor, product, amount, subtract=subtract)
        kind, change = ("removal", -amount) if subtract else ("restock", amount)
        _record_movement(cursor, updated, kind, change, note=note or None)
        return updated


def add_stock(product_id, amount, *, note=None):
    return _change_stock(product_id, amount, subtract=False, note=note)


def remove_stock(product_id, amount, *, note=None):
    return _change_stock(product_id, amount, subtract=True, note=note)


def record_sale(product_id, amount, request_id: UUID | None = None):
    try:
        with connect_db() as connection, connection.cursor() as cursor:
            product = _read_product(cursor, product_id, lock=True)
            amount = stock_amount(amount, product.unit, positive=True)
            if request_id is not None:
                cursor.execute(
                    "SELECT product_id, quantity, unit_price FROM sales WHERE request_id = %s",
                    (request_id,),
                )
                previous = cursor.fetchone()
                if previous:
                    if previous[:2] != (product_id, amount):
                        raise InventoryError("Open a new sale form to record a different sale.", status=409)
                    return SaleResult(product, amount, previous[2], replayed=True)

            product = _update_quantity(cursor, product, amount, subtract=True)
            cursor.execute(
                """
                INSERT INTO sales (product_id, quantity, unit_price, request_id)
                VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (product_id, amount, product.price, request_id),
            )
            sale_id = cursor.fetchone()[0]
            _record_movement(cursor, product, "sale", -amount, sale_id=sale_id)
            return SaleResult(product, amount, product.price)
    except UniqueViolation as error:
        if error.diag.constraint_name != "sales_request_id_key":
            raise
        raise InventoryError("Open a new sale form to record a different sale.", status=409) from None


def quantity_label(quantity, unit):
    number = f"{quantity:,.3f}".rstrip("0").rstrip(".")
    label = "pieces" if unit == "piece" and quantity != 1 else unit
    return f"{number} {label}"


def get_product_categories():
    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT name FROM categories ORDER BY name_key")
        return [category for (category,) in cursor.fetchall()]


def add_category(name):
    name = clean_category_name(name, required=True)
    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO categories (name) VALUES (%s)
            ON CONFLICT (name_key) DO NOTHING
            RETURNING name
            """,
            (name,),
        )
        inserted = cursor.fetchone()
        if inserted:
            return inserted[0], True
        cursor.execute("SELECT name FROM categories WHERE name_key = lower(%s)", (name,))
        return cursor.fetchone()[0], False


def get_products():
    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id, name, price, quantity, min_stock, category, unit FROM products ORDER BY id")
        return cursor.fetchall()


def _page_window(total, page, page_size):
    pages = max(1, (total + page_size - 1) // page_size)
    number = min(max(1, page), pages)
    return number, pages, (number - 1) * page_size


def get_product_page(*, search, category, unit, low, sort, page, page_size=15):
    conditions, params = [], []
    if search:
        if search.isascii() and search.isdecimal():
            conditions.append("id::text = %s")
            params.append(search.lstrip("0") or "0")
        else:
            conditions.append("strpos(lower(name), lower(%s)) > 0")
            params.append(search)
    if category:
        conditions.append("lower(trim(category)) = lower(%s)")
        params.append(category)
    if unit:
        conditions.append("COALESCE(unit, 'piece') = %s")
        params.append(unit)
    if low:
        conditions.append("COALESCE(quantity, 0) < COALESCE(min_stock, 0)")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order = SORTS[sort]

    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute(f"SELECT count(*) FROM products{where}", params)
        total = cursor.fetchone()[0]
        number, pages, offset = _page_window(total, page, page_size)
        cursor.execute(
            f"SELECT {PRODUCT_COLUMNS} FROM products{where} ORDER BY {order} LIMIT %s OFFSET %s",
            [*params, page_size, offset],
        )
        return Page([Product(*row) for row in cursor.fetchall()], total, number, pages)


def inventory_summary():
    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*),
                   count(*) FILTER (WHERE COALESCE(quantity, 0) < COALESCE(min_stock, 0)),
                   COALESCE(sum(price * quantity), 0)
            FROM products
            """
        )
        return cursor.fetchone()


def get_sales_page(page, page_size=15):
    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute(
            """
            SELECT count(*), COALESCE(sum(quantity * unit_price), 0), count(DISTINCT product_id)
            FROM sales
            """
        )
        summary = cursor.fetchone()
        total = summary[0]
        number, pages, offset = _page_window(total, page, page_size)
        cursor.execute(
            """
            SELECT s.id, p.id, p.name, s.quantity, COALESCE(p.unit, 'piece'), s.unit_price,
                   s.sold_at AT TIME ZONE 'Asia/Karachi'
            FROM sales AS s
            JOIN products AS p ON p.id = s.product_id
            ORDER BY s.sold_at DESC, s.id DESC
            LIMIT %s OFFSET %s
            """,
            (page_size, offset),
        )
        return summary, Page([SaleEntry(*row) for row in cursor.fetchall()], total, number, pages)


def get_sales_report_rows(start, end):
    with connect_db() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT (s.sold_at AT TIME ZONE 'Asia/Karachi')::date AS day,
                   p.id, p.name, COALESCE(p.unit, 'piece') AS unit,
                   count(*), SUM(s.quantity), COALESCE(SUM(s.quantity * s.unit_price), 0),
                   count(*) FILTER (WHERE s.unit_price IS NULL)
            FROM sales AS s
            JOIN products AS p ON p.id = s.product_id
            WHERE s.sold_at >= (%s::timestamp AT TIME ZONE 'Asia/Karachi')
              AND s.sold_at < ((%s::date + 1)::timestamp AT TIME ZONE 'Asia/Karachi')
            GROUP BY day, p.id, p.name, unit
            ORDER BY day, p.id
            """,
            (start, end),
        )
        return cursor.fetchall()
