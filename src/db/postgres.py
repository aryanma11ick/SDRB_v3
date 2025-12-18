from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()


@dataclass(frozen=True)
class DbConfig:
    name: str
    user: str
    password: str
    host: str
    port: int


def _load_config() -> DbConfig:
    missing = [var for var in ("DB_NAME", "DB_USERNAME", "DB_PASSWORD") if not os.getenv(var)]
    if missing:
        raise RuntimeError(f"Missing DB env vars: {', '.join(missing)}")

    return DbConfig(
        name=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USERNAME", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
    )


@contextmanager
def db_connection():
    config = _load_config()
    conn = psycopg2.connect(
        dbname=config.name,
        user=config.user,
        password=config.password,
        host=config.host,
        port=config.port,
        cursor_factory=RealDictCursor,
    )
    try:
        yield conn
    finally:
        conn.close()

