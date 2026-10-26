"""Provision only explicitly named project database/roles. Never touches other databases."""

import secrets
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

root = Path(__file__).resolve().parents[1]
for secret_file in (".env", ".env.migration", "apps/dashboard/.env.local"):
    if (root / secret_file).exists():
        raise SystemExit("Existing secret configuration found; refusing to overwrite")
bootstrap = dotenv_values(root / ".env.bootstrap").get("BOOTSTRAP_DATABASE_URL")
admin = bootstrap or "postgresql://postgres@localhost:5432/postgres"
with psycopg.connect(admin, autocommit=True) as conn:
    if conn.execute("SELECT 1 FROM pg_database WHERE datname='woori_blog_agent'").fetchone():
        raise SystemExit("Database already exists; refusing to overwrite. Use migrate.py.")
    for role in ("woori_owner", "woori_app"):
        if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
            raise SystemExit("Project role already exists; refusing to modify.")
    owner_password, app_password = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    for role, password in [("woori_owner", owner_password), ("woori_app", app_password)]:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
    conn.execute("CREATE DATABASE woori_blog_agent OWNER woori_owner")
    conn.execute("REVOKE ALL ON DATABASE woori_blog_agent FROM PUBLIC")
    conn.execute("GRANT CONNECT ON DATABASE woori_blog_agent TO woori_app")
with psycopg.connect(
    f"postgresql://woori_owner:{owner_password}@localhost:5432/woori_blog_agent"
) as conn:
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    conn.execute("GRANT USAGE ON SCHEMA public TO woori_app")
(root / ".env").write_text(
    f"DATABASE_URL=postgresql://woori_app:{app_password}@localhost:5432/woori_blog_agent\nADMIN_TOKEN={secrets.token_urlsafe(36)}\n",
    encoding="utf-8",
)
(root / ".env.migration").write_text(
    f"MIGRATION_DATABASE_URL=postgresql://woori_owner:{owner_password}@localhost:5432/woori_blog_agent\n",
    encoding="utf-8",
)
(root / "apps/dashboard/.env.local").write_text(
    "ADMIN_TOKEN=" + (root / ".env").read_text().split("ADMIN_TOKEN=")[1], encoding="utf-8"
)
print("Dedicated database and roles created; secrets saved in ignored env files.")
