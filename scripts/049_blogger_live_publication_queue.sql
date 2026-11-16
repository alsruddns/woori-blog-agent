-- Add a distinct Blogger-backed publication-job path. Existing jobs remain fake-only.
ALTER TABLE publishing_jobs DROP CONSTRAINT publishing_jobs_adapter_type_check;
ALTER TABLE publishing_jobs DROP CONSTRAINT publishing_jobs_simulation_only_check;
ALTER TABLE publishing_jobs
  ADD CONSTRAINT publishing_jobs_adapter_type_check
    CHECK (adapter_type IN ('fake','blogger_live')),
  ADD CONSTRAINT publishing_jobs_simulation_adapter_check
    CHECK ((adapter_type='fake' AND simulation_only)
        OR (adapter_type='blogger_live' AND NOT simulation_only)),
  ADD COLUMN oauth_connection_id uuid REFERENCES google_connections(id),
  ADD COLUMN live_stage text,
  ADD COLUMN remote_post_id text,
  ADD CONSTRAINT publishing_jobs_live_shape_check CHECK (
    (adapter_type='fake' AND oauth_connection_id IS NULL AND live_stage IS NULL AND remote_post_id IS NULL)
    OR (adapter_type='blogger_live' AND oauth_connection_id IS NOT NULL
        AND live_stage IN ('draft_needed','draft_created','published'))
  );

ALTER TABLE publishing_records
  ADD COLUMN remote_url text,
  ADD COLUMN remote_status text,
  ADD COLUMN remote_verified_at timestamptz,
  ADD CONSTRAINT publishing_records_remote_url_check
    CHECK (remote_url IS NULL OR (remote_url LIKE 'https://%' AND length(remote_url)<=2048));

CREATE TABLE live_publication_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES publishing_jobs(id),
  attempt_no integer NOT NULL CHECK (attempt_no BETWEEN 1 AND 4),
  operation text NOT NULL CHECK (operation IN ('create_draft','publish_draft')),
  idempotency_key text NOT NULL UNIQUE,
  outcome text NOT NULL CHECK (outcome IN ('requested','succeeded','failed','uncertain','blocked')),
  remote_post_id text,
  http_status integer,
  error_category text,
  metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metadata)='object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,attempt_no,operation)
);
CREATE TRIGGER live_publication_attempt_immutable
  BEFORE UPDATE OR DELETE OR TRUNCATE ON live_publication_attempts
  FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE INDEX live_publication_due_queue
  ON publishing_jobs(available_at,scheduled_at,blog_id)
  WHERE NOT simulation_only AND adapter_type='blogger_live' AND status='queued';
GRANT SELECT,INSERT ON live_publication_attempts TO woori_app;
INSERT INTO audit_events(event_type,payload)
  VALUES ('schema.blogger_live_publication.migrated',
          '{"version":49,"historical_rows_preserved":true,"live_writes_enabled":false,"auto_enabled":false}');
INSERT INTO schema_migrations(version) VALUES (49);
