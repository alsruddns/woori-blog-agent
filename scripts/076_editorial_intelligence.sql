-- Independent editorial assistance. No publication flags or historical evaluations change.
CREATE TABLE editorial_selection_settings (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 weights jsonb NOT NULL, effective_slot timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO editorial_selection_settings(weights,effective_slot) VALUES
 ('{"news_value":25,"freshness":20,"reader_relevance":15,"interest":15,"article_potential":15,"analysis_value":10}', '1970-01-01T00:00:00Z');
CREATE TABLE editorial_query_aliases (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 geo text NOT NULL CHECK(geo ~ '^[A-Z]{2}$'), alias text NOT NULL,
 canonical text NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE editorial_topic_scores (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 topic_id uuid NOT NULL REFERENCES trend_topics(id),
 observation_id uuid NOT NULL REFERENCES trend_observations(id),
 blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 settings_id bigint NOT NULL REFERENCES editorial_selection_settings(id),
 collection_slot timestamptz NOT NULL, engine_version text NOT NULL,
 normalized_query text NOT NULL, score numeric NOT NULL CHECK(score BETWEEN 0 AND 100),
 decision text NOT NULL CHECK(decision IN ('selected','review_candidate','duplicate','low_value','insufficient_context','high_risk')),
 result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(observation_id,blog_id,engine_version)
);
CREATE TABLE editorial_quality_reports (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 import_id uuid NOT NULL REFERENCES external_content_imports(id),
 import_version_id uuid NOT NULL REFERENCES external_content_import_versions(id),
 content_version_id uuid NOT NULL REFERENCES content_versions(id),
 engine_version text NOT NULL, stage text NOT NULL CHECK(stage IN ('static','codex')),
 status text NOT NULL CHECK(status IN ('completed','failed')),
 result jsonb NOT NULL, ai_calls integer NOT NULL DEFAULT 0 CHECK(ai_calls BETWEEN 0 AND 1),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX editorial_quality_cache ON editorial_quality_reports(import_version_id,engine_version,stage) WHERE status='completed';
CREATE TABLE editorial_suggestion_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 report_id uuid NOT NULL REFERENCES editorial_quality_reports(id),
 suggestion_id text NOT NULL, action text NOT NULL CHECK(action IN ('apply','ignore','review')),
 new_version_id uuid REFERENCES external_content_import_versions(id),
 created_at timestamptz NOT NULL DEFAULT now()
);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['editorial_selection_settings','editorial_query_aliases','editorial_topic_scores','editorial_quality_reports','editorial_suggestion_events'] LOOP
 EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE OR TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation()',t||'_immutable',t);
 EXECUTE format('GRANT SELECT,INSERT ON %I TO woori_app',t);
 END LOOP;
END $$;
GRANT USAGE ON SEQUENCE editorial_selection_settings_id_seq,editorial_query_aliases_id_seq,editorial_suggestion_events_id_seq TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES('schema.editorial_intelligence.migrated','{"version":76,"publish_authority":false}');
INSERT INTO schema_migrations(version) VALUES(76);
