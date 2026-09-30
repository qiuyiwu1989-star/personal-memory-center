"""Small DB-API adapter for the module's fixed SQL; shared domain logic stays in Store."""
from contextlib import contextmanager
import re

class Connection:
    def __init__(self, connection):
        self.connection = connection
    def execute(self, sql, params=()):
        if sql == 'BEGIN IMMEDIATE':
            # Serialize short write transactions across REST, MCP and worker processes.
            return self.connection.execute('SELECT pg_advisory_xact_lock(7169283401)')
        return self.connection.execute(sql.replace('?', '%s'), params)
    def executescript(self, script):
        for sql in script.split(';'):
            if sql.strip():
                self.execute(re.sub(r'\bREAL\b', 'DOUBLE PRECISION', sql))

@contextmanager
def connect(dsn):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(dsn, row_factory=dict_row, options='-c search_path=memory_center -c statement_timeout=15000 -c lock_timeout=10000') as connection:
        yield Connection(connection)
