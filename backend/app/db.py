from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_settings = get_settings()
_pool = ConnectionPool(
    conninfo=_settings.database_url,
    min_size=1,
    max_size=10,
    kwargs={"row_factory": dict_row},
    open=False,
)


def open_pool() -> None:
    _pool.open(wait=True)


def close_pool() -> None:
    _pool.close()


@contextmanager
def get_connection():
    with _pool.connection() as connection:
        yield connection
