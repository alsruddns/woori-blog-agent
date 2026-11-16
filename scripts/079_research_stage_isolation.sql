CREATE TABLE research_stage_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), stage text NOT NULL CHECK(stage IN ('trends_collection','topic_evaluation','research_import','manuscript_generation')),
 scope_key text NOT NULL, engine_version text NOT NULL, settings_id bigint NOT NULL DEFAULT 0,
 status text NOT NULL CHECK(status IN ('running','completed','partial','failed','paused','superseded')),
 owner_pid integer NOT NULL, attempt integer NOT NULL DEFAULT 1,
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(), last_progress_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 completed_at timestamptz, checkpoint text NOT NULL DEFAULT 'claimed', processed integer NOT NULL DEFAULT 0,
 remaining integer, elapsed_ms bigint, error_category text, result jsonb NOT NULL DEFAULT '{}',
 UNIQUE(stage,scope_key,engine_version,settings_id)
);
CREATE INDEX research_stage_recent ON research_stage_runs(stage,last_progress_at DESC);
CREATE INDEX trends_slots_by_slot ON trend_collection_slots(slot_at,geo);
-- Cache identity includes immutable selection settings, separate from engine version.
ALTER TABLE editorial_topic_scores DROP CONSTRAINT editorial_topic_scores_observation_id_blog_id_engine_versio_key;
ALTER TABLE editorial_topic_scores ADD UNIQUE(observation_id,blog_id,settings_id,engine_version);
GRANT SELECT,INSERT,UPDATE ON research_stage_runs TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES('schema.research_stage_isolation.migrated',
 '{"version":79,"historical_data_preserved":true,"publication_policy_changed":false}');
INSERT INTO schema_migrations(version) VALUES(79);
