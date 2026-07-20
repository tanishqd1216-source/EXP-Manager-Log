import sqlite3
c = sqlite3.connect('database.db')
c.row_factory = sqlite3.Row
row = c.execute('SELECT [Timestamp], [date], [created_at], [Appointment Date] FROM users WHERE [Timestamp] IS NOT NULL LIMIT 1').fetchone()
if row:
    print(dict(row))
else:
    print("No rows found with Timestamp")
