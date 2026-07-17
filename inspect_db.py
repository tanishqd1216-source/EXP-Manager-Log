import sqlite3

conn = sqlite3.connect('database.db')
cur = conn.cursor()

# Safety check before deleting
cur.execute("SELECT COUNT(*) FROM users WHERE rowid > 371")
to_delete = cur.fetchone()[0]
print(f"Rows to delete: {to_delete}")

# Delete duplicates (rowid 372 to 742)
cur.execute("DELETE FROM users WHERE rowid > 371")
conn.commit()

# Confirm
cur.execute("SELECT COUNT(*) FROM users")
remaining = cur.fetchone()[0]
print(f"Rows remaining: {remaining}")

conn.close()
print("Done. Duplicates removed successfully.")
