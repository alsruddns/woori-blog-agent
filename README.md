# woori-blog-agent

Local-first multilingual Blogger operations foundation. Phase 1 provides a Next.js dashboard, FastAPI management API, PostgreSQL append-only audit log, content version schema and durable diagnostic Python worker. It does **not** generate or publish content.

## Requirements and setup
Windows, Node 22+, Python 3.13+, PostgreSQL 16, npm and Git. No Docker.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock.txt
.venv/Scripts/python -m pip install -e . --no-deps
npm --prefix apps/dashboard ci
```

Provision on a fresh installation only: create ignored `.env.bootstrap` containing `BOOTSTRAP_DATABASE_URL` for an administrator, then run `.venv/Scripts/python scripts/bootstrap.py`. It refuses existing project databases/roles and never migrates other databases. Existing local setup is already provisioned: do not rerun bootstrap.

```powershell
.venv/Scripts/python scripts/migrate.py
./scripts/run-api.ps1
# Separate terminal, from repository root:
./scripts/run-worker.ps1
# Separate terminal:
npm --prefix apps/dashboard run dev
```

Open http://127.0.0.1:3000. API listens on 127.0.0.1:8000. Root `.env` contains runtime database credentials and a random administrator bearer token; dashboard `.env.local` contains only that token, used server-side. Never prefix it with NEXT_PUBLIC. `.env.migration` is reserved for database owner tools. `.env.bootstrap` is never loaded by API/worker.

The local dashboard is viewable and editable by trusted local OS users; API administration requires the bearer token. Do not expose either port externally. Future remote operation requires dashboard authentication and TLS.

## Validation
```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy services/api/woori
npm run lint
npm run build
npm run typecheck
```
Integration tests require the dedicated migrated PostgreSQL database and append identifiable diagnostic events permanently. No test deletes audit history.

See [architecture](docs/architecture/overview.md), [operations](docs/operations/runbook.md), [audit](docs/audit/events.md), [decisions](docs/decisions/0001-foundation.md), [development record](docs/development/P1-001.md) and [AGENTS.md](AGENTS.md).

## Multilingual configuration
Open http://127.0.0.1:3000/config to manage languages, multiple blogs per language, country profiles, policy schedules, categories and glossaries. The initial four user-provided Blogspot addresses are registered; Google Blog IDs remain unverified/NULL. No Blogger requests are performed. API/worker startup never loads administrator or migration-owner credentials.

Apply updates using `.venv/Scripts/python scripts/migrate.py` (latest version: 4). Migration 001 is unchanged. Existing version IDs/content and audit records are preserved. Back up the dedicated database first. Configuration tests roll back synthetic records; diagnostic worker tests still append identifiable run history.

BCP 47 tags are normalized (e.g. pt-br -> pt-BR); language identity cannot be renamed in place. Deactivate an old identity and register a replacement to preserve references. New languages receive a default country profile with every capability unverified. Neither registration nor policy activation enables automatic publishing. Country-specific settings are saved as complete profiles, so review all fields before updating an existing language/country pair.

The summary API preserves its language-code array and adds language_details/blogs. The authenticated /admin/config API supports typed registration and safe updates; no delete, Blog ID editing, capability verification or automatic publishing switch is exposed. The dashboard proxy accepts same-origin JSON from loopback port 3000 only.

See [data model](docs/architecture/data-model.md), [multilingual decision](docs/decisions/0002-multilingual.md) and [development record](docs/development/P1-003.md). Search performance storage/display is implemented; data collection and actual language-specific SEO validation remain deferred.
