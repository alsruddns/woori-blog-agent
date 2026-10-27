# Evaluation database credentials

The evaluation migration URL in `.env.evaluation-migration` is a local secret. Never display or copy the file contents into a terminal transcript, chat, test output, audit payload, or development record. Use `python scripts/report-evaluation-db-config.py` when connection identity needs inspection; it reports only scheme, role, host, port, database, and whether a credential is configured.

If a credential has appeared in a tool output, treat it as compromised. First confirm the role's database scope and active sessions without displaying the URL. Rotate only the evaluation migration role, update the ignored file atomically, and verify a fresh connection. Do not rotate administrator, application, reader, or other-project credentials as part of this procedure. If the role is shared or the replacement cannot be verified, record `security_rotation_pending` and do not run evaluation migrations or inference.

The application and read-only roles remain separate from the migration owner. The owner is limited to the evaluation database and must not have `CONNECT` on `woori_blog_agent`. The evaluation runtime also verifies a distinct database name and explicit isolation flag before accepting evaluation work.
