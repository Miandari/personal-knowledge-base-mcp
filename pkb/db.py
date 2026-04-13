"""Connection management, extension loading, schema initialization.

Uses apsw instead of stdlib sqlite3 because macOS system Python is compiled
without enable_load_extension support. apsw provides its own SQLite build
that supports loading sqlite-vec.

The DictCursor wrapper provides dict-like row access (row["field"]) so the
rest of the codebase can use the same patterns as sqlite3.Row.
"""

from pathlib import Path

import apsw
import sqlite_vec

from . import config

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class DictRow(dict):
    """A dict subclass that also supports index-based access for compatibility."""

    def __init__(self, columns: list[str], values: tuple):
        super().__init__(zip(columns, values))
        self._values = values
        self._columns = columns

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class Connection:
    """Wrapper around apsw.Connection providing dict-like row access.

    Usage mirrors sqlite3.Connection but rows are DictRow instances.
    """

    def __init__(self, db_path: str):
        self._conn = apsw.Connection(db_path)
        self._load_extensions()
        self._set_pragmas()

    def _load_extensions(self):
        self._conn.enable_load_extension(True)
        self._conn.load_extension(sqlite_vec.loadable_path())
        self._conn.enable_load_extension(False)

    def _set_pragmas(self):
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.set_busy_timeout(5000)

    def execute(self, sql: str, params=None) -> "Cursor":
        """Execute SQL and return a Cursor with dict-like rows."""
        return Cursor(self._conn, sql, params)

    def executemany(self, sql: str, seq_of_params):
        """Execute SQL for each set of params."""
        for params in seq_of_params:
            self._conn.execute(sql, params)

    def executescript(self, sql: str):
        """Execute multiple SQL statements (like sqlite3.executescript)."""
        self._conn.execute(sql)

    def commit(self):
        """No-op: apsw uses autocommit by default. Use BEGIN/COMMIT explicitly."""
        pass

    def close(self):
        self._conn.close()

    @property
    def raw(self) -> apsw.Connection:
        """Access the underlying apsw connection (for advanced usage)."""
        return self._conn


class Cursor:
    """Wrapper around apsw cursor providing dict-like rows and fetchone/fetchall."""

    def __init__(self, conn: apsw.Connection, sql: str, params=None):
        self._conn = conn
        self._cursor = conn.cursor()
        if params is not None:
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)

        # Eagerly capture column names — must be done before any iteration
        # because apsw's get_description() fails after cursor exhaustion.
        try:
            desc = self._cursor.get_description()
            self._columns: list[str] = [d[0] for d in desc] if desc else []
        except apsw.ExecutionCompleteError:
            self._columns = []

    def fetchone(self) -> DictRow | None:
        try:
            row = next(self._cursor)
            return DictRow(self._columns, row)
        except StopIteration:
            return None

    def fetchall(self) -> list[DictRow]:
        results = []
        for row in self._cursor:
            results.append(DictRow(self._columns, row))
        return results

    def __iter__(self):
        for row in self._cursor:
            yield DictRow(self._columns, row)


def get_connection(db_path: Path | None = None) -> Connection:
    """Open a connection with extensions and pragmas configured."""
    db_path = db_path or config.DB_PATH
    return Connection(str(db_path))


def init_schema(conn: Connection) -> None:
    """Create all tables/indexes from schema.sql if they don't exist."""
    schema_sql = SCHEMA_PATH.read_text()
    # apsw doesn't have executescript, but execute handles multiple statements
    # Split on semicolons but be careful with virtual table definitions
    conn.executescript(schema_sql)


def reset_db(db_path: Path | None = None) -> Connection:
    """Drop the database file and recreate from scratch."""
    db_path = db_path or config.DB_PATH
    if db_path.exists():
        db_path.unlink()
    # Also remove WAL and SHM files
    for suffix in ("-wal", "-shm"):
        wal = db_path.parent / (db_path.name + suffix)
        if wal.exists():
            wal.unlink()
    conn = get_connection(db_path)
    init_schema(conn)
    return conn
