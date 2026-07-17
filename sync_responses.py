import csv
import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable


def _fingerprint(row: dict) -> str:
    payload = "|".join(str(row.get(key, "")) for key in sorted(row))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _normalize_text(value: str) -> str:
    return " ".join(str(value).split()).strip().lower()


def _get_table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]).strip().lower() for row in cursor.fetchall()}


def _find_matching_rowid(cursor: sqlite3.Cursor, table_name: str, payload: dict, column_map: dict[str, str]) -> int | None:
    client_name = None
    for key, value in payload.items():
        if _normalize_text(key) in {"client_name", "customer_name", "client", "client name"}:
            client_name = str(value or "").strip()
            break

    if client_name:
        for normalized_key, actual_name in column_map.items():
            if normalized_key in {"client_name", "customer_name", "client", "client name"}:
                match = cursor.execute(
                    f'SELECT rowid FROM {table_name} WHERE COALESCE("{actual_name}", "") = ?',
                    (client_name,),
                ).fetchone()
                if match:
                    return match[0]

    conditions = []
    values = []
    for key in payload.keys():
        if key == "source_fingerprint":
            continue
        normalized_key = _normalize_text(key)
        if normalized_key not in column_map:
            continue
        actual_name = column_map[normalized_key]
        conditions.append(f'COALESCE("{actual_name}", "") = ?')
        values.append(payload.get(key, ""))

    if conditions:
        match_sql = f'SELECT rowid FROM {table_name} WHERE source_fingerprint IS NULL AND ' + ' AND '.join(conditions)
        match = cursor.execute(match_sql, values).fetchone()
        if match:
            return match[0]

    return None


def sync_rows_into_db(db_path: str | None = None, table_name: str = "users", rows: Iterable[dict] | None = None) -> int:
    db_file = Path(db_path or "database.db")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if cursor.fetchone() is None:
        raise ValueError(f"Table {table_name} does not exist")

    existing_columns = _get_table_columns(cursor, table_name)
    if "source_fingerprint" not in existing_columns:
        cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN source_fingerprint TEXT')
        existing_columns.add("source_fingerprint")

    inserted = 0
    for row in rows or []:
        payload = dict(row)
        payload["source_fingerprint"] = _fingerprint(payload)

        existing = cursor.execute(
            f'SELECT 1 FROM {table_name} WHERE source_fingerprint = ?',
            (payload["source_fingerprint"],),
        ).fetchone()
        if existing:
            continue

        for column_name in payload.keys():
            if column_name == "source_fingerprint":
                continue
            column_name_clean = str(column_name).strip()
            if not column_name_clean:
                continue
            normalized_name = column_name_clean.lower()
            if normalized_name not in existing_columns:
                existing_columns = _get_table_columns(cursor, table_name)
                if normalized_name not in existing_columns:
                    cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {_quote_identifier(column_name_clean)} TEXT')
                    existing_columns.add(normalized_name)

        columns = [key for key in payload.keys() if key != "source_fingerprint"]
        columns = [str(key).strip() for key in columns if str(key).strip()]
        column_map = {row[1].strip().lower(): row[1] for row in cursor.execute(f'PRAGMA table_info({table_name})').fetchall()}

        matched_rowid = _find_matching_rowid(cursor, table_name, payload, column_map)
        if matched_rowid is not None:
            cursor.execute(f'UPDATE {table_name} SET source_fingerprint = ? WHERE rowid = ?', (payload["source_fingerprint"], matched_rowid))
            continue

        placeholders = ", ".join("?" for _ in columns)
        values = [payload.get(key, "") for key in columns]
        col_names = ", ".join('"' + c + '"' for c in columns)
        insert_sql = f'INSERT INTO {table_name} ({col_names}, "source_fingerprint") VALUES ({placeholders}, ?)'
        cursor.execute(insert_sql, values + [payload["source_fingerprint"]])
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def import_sheet_rows(csv_path: str | None = None, db_path: str | None = None, table_name: str = "users") -> int:
    csv_file = Path(csv_path or "")
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_file}")

    with csv_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    return sync_rows_into_db(db_path=db_path, table_name=table_name, rows=rows)
