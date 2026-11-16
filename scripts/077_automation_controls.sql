CREATE TABLE automation_controls (
 id integer PRIMARY KEY CHECK(id=1), revision bigint NOT NULL DEFAULT 1,
 auto_manuscript_enabled boolean NOT NULL DEFAULT true,
 auto_publishing_enabled boolean NOT NULL DEFAULT false,
 manual_publishing_enabled boolean NOT NULL DEFAULT true,
 auto_mode text NOT NULL DEFAULT 'draft' CHECK(auto_mode IN ('draft','publish')),
 auto_blog_ids uuid[] NOT NULL DEFAULT '{}',
 auto_epoch uuid NOT NULL DEFAULT gen_random_uuid(),
 manual_epoch uuid NOT NULL DEFAULT gen_random_uuid(),
 auto_enabled_at timestamptz,
 manual_enabled_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 google_account_report text NOT NULL DEFAULT 'unverified' CHECK(google_account_report IN ('unverified','user_reported_available','restricted')),
 read_check_result jsonb NOT NULL DEFAULT '{}',
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO automation_controls(id) VALUES(1);
CREATE TABLE automation_publication_grants (
 job_id uuid PRIMARY KEY REFERENCES publishing_jobs(id),
 epoch uuid NOT NULL, lane text NOT NULL CHECK(lane IN ('manual','auto')),
 publication_mode text NOT NULL CHECK(publication_mode IN ('draft','publish')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER automation_grants_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON automation_publication_grants
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TABLE automation_runtime_ack (
 service_name text PRIMARY KEY, process_id integer NOT NULL, revision bigint NOT NULL,
 engine_version text NOT NULL, last_seen_at timestamptz NOT NULL
);
GRANT SELECT,UPDATE ON automation_controls TO woori_app;
GRANT SELECT,INSERT ON automation_publication_grants TO woori_app;
GRANT SELECT,INSERT,UPDATE ON automation_runtime_ack TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES('schema.automation_controls.migrated',
 '{"version":77,"auto_publishing_enabled":false,"existing_jobs_granted":false}');
INSERT INTO schema_migrations(version) VALUES(77);
