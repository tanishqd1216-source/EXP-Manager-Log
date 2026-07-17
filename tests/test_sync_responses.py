import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sync_responses import sync_rows_into_db


class SyncResponsesTest(unittest.TestCase):
    def test_sync_rows_inserts_new_rows_and_skips_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE users (name TEXT, email TEXT)")
            conn.commit()
            conn.close()

            rows = [
                {"name": "Asha", "email": "asha@example.com"},
                {"name": "Asha", "email": "asha@example.com"},
            ]

            sync_rows_into_db(db_path=str(db_path), table_name="users", rows=rows)

            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            fingerprints = conn.execute("SELECT source_fingerprint FROM users").fetchall()
            conn.close()

            self.assertEqual(count, 1)
            self.assertTrue(all(fp[0] for fp in fingerprints))

    def test_sync_rows_reuses_existing_columns_on_second_run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE users (name TEXT, email TEXT)")
            conn.commit()
            conn.close()

            first_rows = [{"name": "Asha", "email": "asha@example.com", "Final_Status": "Pending"}]
            second_rows = [{"name": "Asha", "email": "asha@example.com", "Final_Status": "Completed"}]

            sync_rows_into_db(db_path=str(db_path), table_name="users", rows=first_rows)
            sync_rows_into_db(db_path=str(db_path), table_name="users", rows=second_rows)

            conn = sqlite3.connect(db_path)
            final_status = conn.execute("SELECT Final_Status FROM users").fetchall()
            conn.close()

            self.assertEqual(final_status[0][0], "Pending")

    def test_sync_rows_dedupes_existing_rows_without_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE users (name TEXT, email TEXT)")
            conn.execute("INSERT INTO users (name, email) VALUES (?, ?)", ("Asha", "asha@example.com"))
            conn.commit()
            conn.close()

            sync_rows_into_db(db_path=str(db_path), table_name="users", rows=[{"name": "Asha", "email": "asha@example.com"}])

            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            conn.close()

            self.assertEqual(count, 1)

    def test_sync_rows_dedupes_rows_with_same_client_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE users (\"Client Name\" TEXT, \"Appointment Type\" TEXT)")
            conn.commit()
            conn.close()

            first_rows = [{"Client Name": "Asha", "Appointment Type": "Consultation"}]
            second_rows = [{"Client Name": "Asha", "Appointment Type": "Vaccination"}]

            sync_rows_into_db(db_path=str(db_path), table_name="users", rows=first_rows)
            sync_rows_into_db(db_path=str(db_path), table_name="users", rows=second_rows)

            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            row = conn.execute('SELECT "Client Name", "Appointment Type" FROM users').fetchone()
            conn.close()

            self.assertEqual(count, 1)
            self.assertEqual(row[0], "Asha")
            self.assertEqual(row[1], "Consultation")


if __name__ == "__main__":
    unittest.main()
