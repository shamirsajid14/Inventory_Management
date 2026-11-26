from pathlib import Path
from uuid import uuid4

from psycopg import sql
import pytest

from database import connect_db
import models


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def test_database():
    name = f"inventory_test_{uuid4().hex}"
    identifier = sql.Identifier(name)
    with connect_db(dbname="postgres", autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(identifier))
    try:
        def connect():
            connection = connect_db(dbname=name)
            if connection.info.dbname != name:
                connection.close()
                raise RuntimeError("Integration tests reached an unexpected database.")
            return connection

        with connect() as connection:
            connection.autocommit = True
            for script in ("schema.sql", "categories.sql", "migrations/001_stock_movements.sql"):
                connection.execute((ROOT / script).read_text(encoding="utf-8"))
        yield connect
    finally:
        with connect_db(dbname="postgres", autocommit=True) as maintenance:
            maintenance.execute(sql.SQL("DROP DATABASE {}").format(identifier))


@pytest.fixture(autouse=True)
def isolated_inventory(test_database, monkeypatch):
    monkeypatch.setattr(models, "connect_db", test_database)
    with test_database() as connection:
        connection.execute("TRUNCATE stock_movements, sales, products, categories RESTART IDENTITY")
