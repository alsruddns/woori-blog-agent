-- Durable scheduling and bounded recovery for fake-only publication simulations.
ALTER TABLE publishing_jobs
 ADD COLUMN attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 4),
 ADD COLUMN retry_count integer NOT NULL DEFAULT 0 CHECK(retry_count BETWEEN 0 AND 3),
 ADD COLUMN max_retries integer NOT NULL DEFAULT 2 CHECK(max_retries BETWEEN 0 AND 3),
 ADD COLUMN lease_until timestamptz,
 ADD COLUMN available_at timestamptz NOT NULL DEFAULT now(),
 ADD COLUMN schedule_timezone text NOT NULL DEFAULT 'UTC',
 ADD COLUMN mock_scenario text NOT NULL DEFAULT 'success'
   CHECK(mock_scenario IN ('success','timeout','auth_failure','server_failure','uncertain')),
 ADD COLUMN last_error_category text;
CREATE INDEX publication_due_queue ON publishing_jobs(status,scheduled_at,available_at)
 WHERE simulation_only AND adapter_type='fake' AND status='queued';
ALTER TABLE publication_attempts
 ADD COLUMN attempt_no integer NOT NULL DEFAULT 1 CHECK(attempt_no BETWEEN 1 AND 4),
 ADD COLUMN attempt_kind text NOT NULL DEFAULT 'interactive'
   CHECK(attempt_kind IN ('interactive','worker')),
 ADD COLUMN retryable boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX publication_attempt_job_number ON publication_attempts(job_id,attempt_no,attempt_kind);
CREATE TABLE publication_schedule_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 job_id uuid NOT NULL REFERENCES publishing_jobs(id),
 idempotency_key text NOT NULL UNIQUE,
 action text NOT NULL CHECK(action IN ('scheduled','rescheduled','cancelled')),
 scheduled_at timestamptz,
 timezone text NOT NULL,
 details jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(details)='object'),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TRIGGER publication_schedule_event_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON publication_schedule_events FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
ALTER TABLE worker_heartbeats DROP CONSTRAINT worker_heartbeats_service_name_check;
ALTER TABLE worker_heartbeats ADD CONSTRAINT worker_heartbeats_service_name_check
 CHECK(service_name IN ('research_worker','evaluation_worker','publication_worker'));
GRANT SELECT,INSERT ON publication_schedule_events TO woori_app;
GRANT USAGE,SELECT ON SEQUENCE publication_schedule_events_id_seq TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.publication_scheduling.migrated','{"version":26,"mock_worker_only":true,"real_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(26);
