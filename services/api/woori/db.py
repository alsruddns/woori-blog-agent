import ipaddress
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import settings


@contextmanager
def connection() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    with psycopg.connect(settings().database_url, row_factory=dict_row) as conn:
        if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
            identity = conn.execute(
                "SELECT current_database() AS database_name,current_user AS role_name,"
                "inet_server_addr()::text AS server_address"
            ).fetchone()
            server_address = str(identity["server_address"] or "").split("/", maxsplit=1)[0] if identity else ""
            try:
                loopback_server = ipaddress.ip_address(server_address).is_loopback
            except ValueError:
                loopback_server = False
            if (
                not identity
                or identity["database_name"] != "woori_blog_agent_test"
                or identity["role_name"] != "woori_test_app"
                or not loopback_server
            ):
                raise RuntimeError("Database-backed tests require the isolated local test database identity")
            # Every application/worker connection opened by pytest gets its own
            # forced rollback boundary. Integration tests that need shared
            # visibility still patch connection() to their outer rollback lab.
            with conn.transaction(force_rollback=True):
                yield conn
        else:
            yield conn
