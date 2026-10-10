import sqlite3

with sqlite3.connect(':memory:') as conn:
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE test (id INTEGER, status TEXT)')
    conn.execute("INSERT INTO test VALUES (1, 'ok')")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM test WHERE status='ok'")
    raw_row = cur.fetchone()
    print('Type:', type(raw_row))
    print('dict(row):', dict(raw_row))
    print('Keys:', list(raw_row.keys()))
