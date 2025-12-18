from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError as exc:  # pragma: no cover - helper script
    raise SystemExit(
        "psycopg2 is required. Install with `pip install psycopg2-binary` inside your venv."
    ) from exc


@dataclass
class DbConfig:
    name: str
    user: str
    password: str
    host: str = "localhost"
    port: int = 5432


def load_config() -> DbConfig:
    load_dotenv()

    missing = [var for var in ("DB_NAME", "DB_USERNAME", "DB_PASSWORD") if not os.getenv(var)]
    if missing:
        raise SystemExit(f"Missing DB env vars: {', '.join(missing)}")

    return DbConfig(
        name=os.getenv("DB_NAME", "postgres"),
        user=os.getenv("DB_USERNAME", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
    )


def test_connection() -> None:
    config = load_config()
    print(f"Connecting to PostgreSQL at {config.host}:{config.port} / db={config.name}")

    conn = psycopg2.connect(
        dbname=config.name,
        user=config.user,
        password=config.password,
        host=config.host,
        port=config.port,
        cursor_factory=RealDictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok;")
            result = cur.fetchone()
            print("Health check:", result)

            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
                """
            )
            tables = cur.fetchall()
            print("Public schema tables:")
            for row in tables:
                print(" -", row["table_name"])
    finally:
        conn.close()
        print("Connection closed.")


if __name__ == "__main__":
    try:
        test_connection()
    except Exception as exc:  # pragma: no cover
        print("Connection test failed:", exc)
        sys.exit(1)
