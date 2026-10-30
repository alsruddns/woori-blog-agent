-- Additive editorial state. Existing observations, topics and reviews remain immutable.
ALTER TABLE trend_observations ADD COLUMN raw_payload jsonb,
 ADD COLUMN source_categories text[] NOT NULL DEFAULT '{}';
CREATE TABLE trend_collection_slots (
 geo text NOT NULL, slot_at timestamptz NOT NULL,
 run_id uuid REFERENCES trend_collection_runs(id), result jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(geo,slot_at)
);
CREATE TABLE trend_editorial_events (
 id bigserial PRIMARY KEY, topic_id uuid NOT NULL REFERENCES trend_topics(id),
 previous_state text, state text NOT NULL CHECK(state IN
 ('collected','pending_classification','selected','review_candidate','discarded','generation_queued','generating','imported','published','failed')),
 reason_code text NOT NULL, reason text NOT NULL CHECK(length(reason) BETWEEN 3 AND 2000),
 actor text NOT NULL, category text, evidence jsonb NOT NULL DEFAULT '{}',
 request_key uuid NOT NULL UNIQUE, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX trend_editorial_latest ON trend_editorial_events(topic_id,id DESC);
CREATE TRIGGER trend_editorial_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_editorial_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TABLE trend_generation_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), topic_id uuid NOT NULL REFERENCES trend_topics(id),
 duplicate_key text NOT NULL UNIQUE, contract jsonb NOT NULL,
 state text NOT NULL DEFAULT 'generation_queued' CHECK(state IN ('generation_queued','generating','imported','published','failed','cancelled')),
 authoring_job_id uuid UNIQUE REFERENCES codex_authoring_jobs(id),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT,INSERT ON trend_editorial_events TO woori_app;
GRANT USAGE,SELECT ON SEQUENCE trend_editorial_events_id_seq TO woori_app;
GRANT SELECT,INSERT,UPDATE ON trend_collection_slots,trend_generation_requests TO woori_app;
CREATE INDEX trend_observations_time_geo ON trend_observations(collected_at DESC,geo);
CREATE INDEX trend_membership_observation ON trend_topic_memberships(observation_id,created_at DESC);
INSERT INTO audit_events(event_type,payload) VALUES('schema.trend_editorial_queue.migrated',
 '{"version":62,"historical_observations_preserved":true,"generation_not_connected":true}');
INSERT INTO schema_migrations(version) VALUES(62);
