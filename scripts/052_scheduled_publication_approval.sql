-- Append-only, scheduled-export-only operations approval. This does not alter
-- the legacy operations_auto_approved CHECK or authorize existing/manual jobs.
CREATE TABLE scheduled_publication_policy_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 action text NOT NULL CHECK (action IN ('enabled','disabled')),
 approved_blog_ids jsonb NOT NULL CHECK (jsonb_typeof(approved_blog_ids)='array'),
 daily_limit smallint NOT NULL DEFAULT 1 CHECK (daily_limit BETWEEN 1 AND 3),
 actor_label text NOT NULL CHECK (length(trim(actor_label)) BETWEEN 2 AND 120),
 reason text NOT NULL CHECK (length(trim(reason)) BETWEEN 10 AND 2000),
 idempotency_key text NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 16 AND 128),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK (action <> 'enabled' OR jsonb_array_length(approved_blog_ids) BETWEEN 1 AND 4)
);
CREATE TABLE scheduled_first_publication_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 action text NOT NULL CHECK (action IN ('approved','revoked')),
 blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 import_id uuid NOT NULL REFERENCES external_content_imports(id),
 import_version_id uuid NOT NULL REFERENCES external_content_import_versions(id),
 content_version_id uuid NOT NULL REFERENCES content_versions(id),
 body_sha256 char(64) NOT NULL CHECK (body_sha256 ~ '^[0-9a-f]{64}$'),
 actor_label text NOT NULL CHECK (length(trim(actor_label)) BETWEEN 2 AND 120),
 reason text NOT NULL CHECK (length(trim(reason)) BETWEEN 10 AND 2000),
 idempotency_key text NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 16 AND 128),
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE publishing_jobs ADD COLUMN publication_lane text NOT NULL DEFAULT 'manual'
 CHECK (publication_lane IN ('manual','scheduled_auto'));
CREATE INDEX scheduled_auto_jobs_due ON publishing_jobs(available_at,scheduled_at,blog_id)
 WHERE publication_lane='scheduled_auto' AND NOT simulation_only
   AND adapter_type='blogger_live' AND status='queued';
CREATE TRIGGER scheduled_publication_policy_events_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON scheduled_publication_policy_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER scheduled_first_publication_events_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON scheduled_first_publication_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON scheduled_publication_policy_events,scheduled_first_publication_events TO woori_app;
GRANT USAGE,SELECT ON SEQUENCE scheduled_publication_policy_events_id_seq,
 scheduled_first_publication_events_id_seq TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.scheduled_publication_approval.migrated',
  '{"version":52,"enabled":false,"existing_jobs_lane":"manual","legacy_check_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(52);
