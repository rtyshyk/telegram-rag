"""Simple migration script to verify database connectivity."""

import os

import psycopg2


def migrate() -> None:
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn)
    conn.close()


if __name__ == "__main__":
    migrate()
