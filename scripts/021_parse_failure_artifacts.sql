CREATE TABLE model_failure_artifacts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 batch_id uuid NOT NULL,
 topic_key text NOT NULL,
 language_code text NOT NULL REFERENCES languages(code),
 model text NOT NULL,
 prompt_version text NOT NULL,
 error_category text NOT NULL CHECK(error_category IN ('local_model_json_invalid','local_model_output_schema_invalid')),
 response_sha256 char(64) NOT NULL,
 response_excerpt text NOT NULL CHECK(length(response_excerpt)<=16384),
 response_chars integer NOT NULL CHECK(response_chars>=length(response_excerpt)),
 truncated boolean NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(batch_id,topic_key,language_code,response_sha256)
);
CREATE TRIGGER model_failure_artifacts_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON model_failure_artifacts
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE INDEX model_failure_artifacts_recent ON model_failure_artifacts(created_at DESC);
GRANT SELECT,INSERT ON model_failure_artifacts TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.parse_failure_artifacts.migrated','{"version":21}');
INSERT INTO schema_migrations(version) VALUES(21);
