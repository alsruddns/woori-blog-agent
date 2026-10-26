from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import settings


@contextmanager
def connection() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    with psycopg.connect(settings().database_url, row_factory=dict_row) as conn:
        yield conn
