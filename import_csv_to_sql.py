import csv
import os
import re
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "Experience Manager@Cx - Today.csv"
DB_FILE = BASE_DIR / "database.db"
TABLE_NAME = "users"


def clean_header(header):
    header = (header or "").strip()
    if not header:
        return "column"
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", header).strip("_").lower()
    return cleaned or "column"


def normalize_header(header, used_headers):
    base = clean_header(header)
    candidate = base
    counter = 1
    while candidate in used_headers:
        candidate = f"{base}_{counter}"
        counter += 1
    used_headers.add(candidate)
    return candidate


def find_header_row(reader):
    for index, row in enumerate(reader):
        if not row:
            continue
        normalized = [cell.strip().lower() for cell in row if cell is not None]
        if any("appt" in cell and "id" in cell for cell in normalized):
            return index, row
        if any("start_time" in cell for cell in normalized):
            return index, row
    return None, None


def main():
    if not CSV_FILE.exists():
        raise FileNotFoundError(f"CSV file not found: {CSV_FILE}")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")

    with open(CSV_FILE, mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header_index, header_row = find_header_row(reader)
        if header_index is None or header_row is None:
            raise ValueError("Could not find the header row in the CSV file.")

        used_headers = set()
        headers = [normalize_header(h, used_headers) for h in header_row]
        columns_sql = ", ".join([f'"{h}" TEXT' for h in headers])
        create_table_sql = f"CREATE TABLE {TABLE_NAME} ({columns_sql});"
        cursor.execute(create_table_sql)

        quoted_headers = ", ".join(f'"{h}"' for h in headers)
        placeholders = ", ".join("?" for _ in headers)
        insert_sql = f"INSERT INTO {TABLE_NAME} ({quoted_headers}) VALUES ({placeholders})"

        batch = []
        batch_size = 1000
        inserted = 0

        for row in reader:
            if not any((cell or "").strip() for cell in row):
                continue

            row_data = []
            for index, value in enumerate(row):
                if index < len(headers):
                    row_data.append(value or "")
                else:
                    row_data.append("")

            if len(row_data) < len(headers):
                row_data.extend([""] * (len(headers) - len(row_data)))

            batch.append(tuple(row_data[:len(headers)]))
            inserted += 1

            if len(batch) >= batch_size:
                cursor.executemany(insert_sql, batch)
                conn.commit()
                batch = []

        if batch:
            cursor.executemany(insert_sql, batch)
            conn.commit()

    conn.close()
    print(f"Imported {inserted} rows into {TABLE_NAME} from {CSV_FILE.name}")


if __name__ == "__main__":
    main()
