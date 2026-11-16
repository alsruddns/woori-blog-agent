CREATE TABLE google_connections (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), label text NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','connected','error','revoked','disconnected')),
 access_ciphertext text, refresh_ciphertext text, expires_at timestamptz,
 scopes text[] NOT NULL DEFAULT '{}', error_category text,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE google_oauth_states (
 state_hash text PRIMARY KEY, binding_hash text NOT NULL,
 connection_id uuid NOT NULL REFERENCES google_connections(id), verifier_ciphertext text NOT NULL,
 expires_at timestamptz NOT NULL, consumed boolean NOT NULL DEFAULT false);
ALTER TABLE blogger_blogs ADD COLUMN oauth_connection_id uuid REFERENCES google_connections(id);
ALTER TABLE blogger_blogs ADD COLUMN connection_error text;
ALTER TABLE blogger_blogs ADD COLUMN last_checked_at timestamptz;
CREATE TABLE blogger_api_calls (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, request_id uuid NOT NULL,
 blog_id uuid REFERENCES blogger_blogs(id), connection_id uuid REFERENCES google_connections(id),
 language_code text REFERENCES languages(code), operation text NOT NULL,
 attempt integer NOT NULL CHECK(attempt>0), status text NOT NULL,
 http_status integer, error_category text, created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX blogger_call_history ON blogger_api_calls(blog_id,created_at DESC);
CREATE INDEX blogger_call_rate ON blogger_api_calls(language_code,created_at DESC);
CREATE TRIGGER blogger_calls_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON blogger_api_calls
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TABLE language_execution_limits (
 language_code text PRIMARY KEY REFERENCES languages(code), read_enabled boolean NOT NULL DEFAULT true,
 requests_per_minute integer NOT NULL DEFAULT 30 CHECK(requests_per_minute BETWEEN 1 AND 60),
 max_page_size integer NOT NULL DEFAULT 20 CHECK(max_page_size BETWEEN 1 AND 100),
 publishing_enabled boolean NOT NULL DEFAULT false CHECK(NOT publishing_enabled));
INSERT INTO language_execution_limits(language_code) SELECT code FROM languages;
CREATE FUNCTION initialize_language_limits() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN INSERT INTO language_execution_limits(language_code) VALUES(NEW.code); RETURN NEW; END; $$;
CREATE TRIGGER initialize_limits AFTER INSERT ON languages FOR EACH ROW EXECUTE FUNCTION initialize_language_limits();
CREATE TRIGGER limits_audit AFTER INSERT OR UPDATE ON language_execution_limits
 FOR EACH ROW EXECUTE FUNCTION audit_configuration();
CREATE TABLE blogger_write_operations (
 idempotency_key text PRIMARY KEY, request_fingerprint text NOT NULL,
 operation text NOT NULL, status text NOT NULL CHECK(status IN ('pending','succeeded','uncertain','failed')),
 result jsonb, created_at timestamptz NOT NULL DEFAULT now());
GRANT SELECT,INSERT,UPDATE ON google_connections,google_oauth_states,language_execution_limits,blogger_write_operations TO woori_app;
GRANT SELECT,INSERT ON blogger_api_calls TO woori_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES('schema.blogger.migrated','{"version":5}');
INSERT INTO schema_migrations(version) VALUES(5);
