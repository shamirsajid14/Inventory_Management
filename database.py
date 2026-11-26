import os
from pathlib import Path

from dotenv import load_dotenv
import psycopg


load_dotenv(Path(__file__).with_name(".env"))


def connect_db(*, dbname=None, autocommit=False):
    return psycopg.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=dbname or os.getenv("PGDATABASE", "inventory_db"),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        autocommit=autocommit,
    )
