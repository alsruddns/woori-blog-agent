CREATE TABLE external_content_imports (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 external_content_id text NOT NULL,
 event_group_id text NOT NULL,
 research_package_id text,
 parent_content_id text,
 relation text NOT NULL CHECK (relation IN ('original','localized','revision')),
 source_region text NOT NULL CHECK (source_region ~ '^([A-Z]{2,3}|[0-9]{3})$'),
 language_code text NOT NULL CHECK (language_code IN ('ko','en','ja','zh-CN')),
 target_audiences jsonb NOT NULL CHECK (jsonb_typeof(target_audiences)='array'),
 category text NOT NULL REFERENCES categories(slug),
 title text NOT NULL,
 body_markdown text NOT NULL,
 source_ids jsonb NOT NULL CHECK (jsonb_typeof(source_ids)='array'),
 sources jsonb NOT NULL CHECK (jsonb_typeof(sources)='array'),
 claims jsonb NOT NULL CHECK (jsonb_typeof(claims)='array'),
 fact_checked_at timestamptz NOT NULL,
 seo_metadata jsonb NOT NULL CHECK (jsonb_typeof(seo_metadata)='object'),
 blogger_labels jsonb NOT NULL CHECK (jsonb_typeof(blogger_labels)='array'),
 generation_method text NOT NULL CHECK (generation_method IN ('manual_codex_import','chatgpt_scheduled_export','other_external_export')),
 model_name text,
 generated_at timestamptz NOT NULL,
 submitted_by text NOT NULL,
 content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
 idempotency_key char(64) NOT NULL UNIQUE CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
 state text NOT NULL DEFAULT 'awaiting_human_review' CHECK (state='awaiting_human_review'),
 generation_ready boolean NOT NULL DEFAULT false CHECK (generation_ready=false),
 publish_ready boolean NOT NULL DEFAULT false CHECK (publish_ready=false),
 received_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(generation_method,external_content_id)
);
CREATE TABLE external_content_import_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 import_id uuid NOT NULL REFERENCES external_content_imports(id),
 event_key text NOT NULL UNIQUE,
 event_type text NOT NULL CHECK (event_type IN ('received')),
 actor text NOT NULL,
 reason text NOT NULL,
 details jsonb NOT NULL CHECK (jsonb_typeof(details)='object'),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER external_content_import_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_imports FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER external_content_import_event_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_import_events FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
INSERT INTO categories(slug) VALUES
 ('economy'),('finance'),('stocks'),('crypto'),('technology'),
 ('semiconductors'),('artificial-intelligence'),('policy')
 ON CONFLICT(slug) DO NOTHING;
GRANT SELECT,INSERT ON external_content_imports,external_content_import_events TO woori_app;
GRANT USAGE,SELECT ON SEQUENCE external_content_import_events_id_seq TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.external_content_imports.migrated',
  '{"version":45,"generator_connected":false,"live_blogger_writes_enabled":false,"publish_ready":false}');
INSERT INTO schema_migrations(version) VALUES(45);
