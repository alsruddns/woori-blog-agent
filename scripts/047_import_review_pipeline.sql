CREATE TABLE external_content_import_versions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 import_id uuid NOT NULL REFERENCES external_content_imports(id),
 version_number integer NOT NULL CHECK (version_number > 0),
 parent_version_id uuid REFERENCES external_content_import_versions(id),
 title text NOT NULL,
 body_markdown text NOT NULL,
 seo_metadata jsonb NOT NULL CHECK (jsonb_typeof(seo_metadata)='object'),
 blogger_labels jsonb NOT NULL CHECK (jsonb_typeof(blogger_labels)='array'),
 content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
 author_label text NOT NULL,
 change_reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(import_id,version_number), UNIQUE(import_id,content_sha256),
 UNIQUE(import_id,id)
);
INSERT INTO external_content_import_versions(import_id,version_number,title,body_markdown,seo_metadata,blogger_labels,
 content_sha256,author_label,change_reason)
SELECT id,1,title,body_markdown,seo_metadata,blogger_labels,
 encode(sha256(convert_to(title || E'\n' || body_markdown || E'\n' || seo_metadata::text || E'\n' || blogger_labels::text,'UTF8')),'hex'),
 submitted_by,'Initial immutable version copied from the imported envelope'
FROM external_content_imports
ON CONFLICT(import_id,version_number) DO NOTHING;
CREATE TABLE external_content_import_assessments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 import_id uuid NOT NULL REFERENCES external_content_imports(id),
 version_id uuid NOT NULL REFERENCES external_content_import_versions(id),
 machine_checks jsonb NOT NULL CHECK (jsonb_typeof(machine_checks)='object'),
 seo_checks jsonb NOT NULL CHECK (jsonb_typeof(seo_checks)='array'),
 machine_passed boolean NOT NULL,
 safe_html text NOT NULL,
 html_sha256 char(64) NOT NULL CHECK (html_sha256 ~ '^[0-9a-f]{64}$'),
 assessed_at timestamptz NOT NULL DEFAULT now(),
 independent_source_verification boolean NOT NULL DEFAULT false CHECK (independent_source_verification=false),
 generation_ready boolean NOT NULL DEFAULT false CHECK (generation_ready=false),
 publish_ready boolean NOT NULL DEFAULT false CHECK (publish_ready=false),
 UNIQUE(import_id,id)
);
CREATE TABLE external_content_import_review_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 import_id uuid NOT NULL REFERENCES external_content_imports(id),
 version_id uuid NOT NULL REFERENCES external_content_import_versions(id),
 assessment_id uuid REFERENCES external_content_import_assessments(id),
 event_type text NOT NULL CHECK (event_type IN ('review_started','changes_requested','editorial_review_passed')),
 reviewer_label text NOT NULL CHECK (length(trim(reviewer_label)) BETWEEN 2 AND 120),
 reason text NOT NULL CHECK (length(trim(reason)) BETWEEN 5 AND 2000),
 sources_examined boolean NOT NULL DEFAULT false,
 claims_checked boolean NOT NULL DEFAULT false,
 rights_reviewed boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE external_content_import_localization_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 import_id uuid NOT NULL REFERENCES external_content_imports(id),
 target_language text NOT NULL CHECK (target_language IN ('ko','en','ja','zh-CN')),
 event_type text NOT NULL CHECK (event_type IN ('requested','cancelled')),
 requester_label text NOT NULL CHECK (length(trim(requester_label)) BETWEEN 2 AND 120),
 reason text NOT NULL CHECK (length(trim(reason)) BETWEEN 5 AND 1000),
 idempotency_key text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE external_content_import_mock_publications (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 import_id uuid NOT NULL REFERENCES external_content_imports(id),
 version_id uuid NOT NULL REFERENCES external_content_import_versions(id),
 idempotency_key text NOT NULL UNIQUE,
 outcome text NOT NULL CHECK (outcome IN ('succeeded','failed','uncertain')),
 fake_post_id text,
 result jsonb NOT NULL CHECK (jsonb_typeof(result)='object'),
 simulation_only boolean NOT NULL DEFAULT true CHECK (simulation_only=true),
 external_network_calls integer NOT NULL DEFAULT 0 CHECK (external_network_calls=0),
 real_blog_mutated boolean NOT NULL DEFAULT false CHECK (real_blog_mutated=false),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER external_import_versions_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_import_versions FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER external_import_assessments_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_import_assessments FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER external_import_reviews_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_import_review_events FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER external_import_localizations_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_import_localization_events FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER external_import_mock_publications_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_import_mock_publications FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON external_content_import_versions,external_content_import_assessments,
 external_content_import_review_events,external_content_import_localization_events,
 external_content_import_mock_publications TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.import_review_pipeline.migrated',
  '{"version":47,"source_assertions_independently_verified":false,"generation_ready":false,"publish_ready":false,"external_network_calls":0}');
INSERT INTO schema_migrations(version) VALUES(47);
