CREATE TABLE codex_authoring_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 request_key uuid NOT NULL UNIQUE,
 request_sha256 text NOT NULL CHECK(length(request_sha256)=64),
 parent_job_id uuid REFERENCES codex_authoring_jobs(id),
 job_type text NOT NULL CHECK(job_type IN ('user_keyword','google_trends')),
 blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 language_code text NOT NULL,
 target_country text NOT NULL,
 category text NOT NULL REFERENCES categories(slug),
 keyword text NOT NULL,
 options jsonb NOT NULL,
 state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','researching','writing','validating','import_pending','imported_review','failed','cancelled')),
 model text NOT NULL,
 execution_path text NOT NULL DEFAULT 'codex_exec_chatgpt',
 execution_id text,
 process_id integer,
 cancel_requested boolean NOT NULL DEFAULT false,
 import_attempts integer NOT NULL DEFAULT 0 CHECK(import_attempts BETWEEN 0 AND 3),
 error_code text,
 result_path text,
 result_sha256 text,
 import_id uuid REFERENCES external_content_imports(id),
 content_version_id uuid REFERENCES content_versions(id),
 evidence jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,
 completed_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT,INSERT,UPDATE ON codex_authoring_jobs TO woori_app;
CREATE INDEX codex_authoring_queue ON codex_authoring_jobs(created_at) WHERE state='queued';
CREATE UNIQUE INDEX codex_authoring_retry_parent ON codex_authoring_jobs(parent_job_id) WHERE parent_job_id IS NOT NULL;
INSERT INTO audit_events(event_type,payload) VALUES ('schema.codex_authoring.migrated','{"version":61,"manual_only":true,"publisher_changes":false}');
INSERT INTO schema_migrations(version) VALUES(61);
