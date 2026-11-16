-- Add an explicitly simulated publication workflow. There is no live adapter.
ALTER TABLE publishing_jobs DROP CONSTRAINT publishing_jobs_status_check;
ALTER TABLE publishing_jobs ADD CONSTRAINT publishing_jobs_status_check
 CHECK(status IN ('blocked','queued','running','succeeded','failed','cancelled','uncertain'));
ALTER TABLE publishing_jobs
 ADD COLUMN publication_state text NOT NULL DEFAULT 'publication_blocked'
   CHECK(publication_state IN ('draft','quality_held','machine_checked','human_review_pending',
     'human_review_rejected','human_review_approved','publication_blocked','publication_queued',
     'publishing','published','publication_failed','cancelled')),
 ADD COLUMN adapter_type text NOT NULL DEFAULT 'fake' CHECK(adapter_type='fake'),
 ADD COLUMN simulation_only boolean NOT NULL DEFAULT true CHECK(simulation_only),
 ADD COLUMN block_reasons jsonb NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(block_reasons)='array'),
 ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
CREATE TABLE publication_state_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 job_id uuid NOT NULL REFERENCES publishing_jobs(id),
 from_state text,
 to_state text NOT NULL,
 reason text NOT NULL,
 details jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(details)='object'),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TRIGGER publication_state_event_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON publication_state_events FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TABLE publication_attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 job_id uuid NOT NULL REFERENCES publishing_jobs(id),
 idempotency_key text NOT NULL UNIQUE,
 adapter_type text NOT NULL DEFAULT 'fake' CHECK(adapter_type='fake'),
 scenario text NOT NULL CHECK(scenario IN ('success','timeout','auth_failure','server_failure','uncertain')),
 outcome text NOT NULL CHECK(outcome IN ('succeeded','failed','uncertain')),
 fake_post_id text CHECK(fake_post_id IS NULL OR fake_post_id LIKE 'fake-post-%'),
 result jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(result)='object'),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TRIGGER publication_attempt_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON publication_attempts FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE INDEX publication_attempt_recent ON publication_attempts(created_at DESC);
GRANT SELECT,INSERT,UPDATE ON publishing_jobs TO woori_app;
GRANT SELECT,INSERT ON publication_state_events,publication_attempts TO woori_app;
GRANT USAGE,SELECT ON SEQUENCE publication_state_events_id_seq TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.publication_safety.migrated','{"version":25,"simulation_only":true,"real_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(25);
