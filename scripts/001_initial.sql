CREATE TABLE schema_migrations(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE job_runs(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), idempotency_key text UNIQUE NOT NULL,
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','succeeded','failed')),
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 available_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz,
 error_type text, error_message text, error_location text, error_at timestamptz, resolution text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX job_queue ON job_runs(status,available_at);
CREATE TABLE audit_events(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, run_id uuid REFERENCES job_runs(id),
 event_type text NOT NULL CHECK(event_type ~ '^[a-z][a-z0-9_.]{1,79}$'),
 payload jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(payload)='object'),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE FUNCTION deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Append-only relation'; END; $$;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TABLE content_groups(id uuid PRIMARY KEY DEFAULT gen_random_uuid());
CREATE TABLE content_versions(
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), group_id uuid NOT NULL REFERENCES content_groups(id),
 language text NOT NULL CHECK(language IN ('ko','en','zh-CN','ja')),
 version integer NOT NULL CHECK(version>0), title text NOT NULL, body text NOT NULL,
 source_version_id uuid REFERENCES content_versions(id), created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(group_id,language,version));
CREATE TRIGGER content_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON content_versions
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON job_runs TO woori_app;
GRANT SELECT,INSERT ON audit_events,content_groups,content_versions TO woori_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO woori_app;
INSERT INTO schema_migrations(version) VALUES(1);
