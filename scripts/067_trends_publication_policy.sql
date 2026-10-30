-- Trends has its own explicit, append-only auto-publication scope.
-- Existing jobs and the scheduled/manual approval lanes are unchanged.
ALTER TABLE publishing_jobs DROP CONSTRAINT publishing_jobs_publication_lane_check;
ALTER TABLE publishing_jobs ADD CONSTRAINT publishing_jobs_publication_lane_check
 CHECK (publication_lane IN ('manual','scheduled_auto','trends_auto'));

CREATE TABLE trends_publication_policy_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 enabled boolean NOT NULL,
 allowed_geos text[] NOT NULL DEFAULT '{}',
 daily_limit smallint NOT NULL DEFAULT 3 CHECK (daily_limit BETWEEN 1 AND 10),
 actor_label text NOT NULL CHECK (length(trim(actor_label)) BETWEEN 2 AND 120),
 reason text NOT NULL CHECK (length(trim(reason)) BETWEEN 10 AND 2000),
 idempotency_key text NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 16 AND 128),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK (cardinality(allowed_geos)<=11),
 CHECK (allowed_geos <@ ARRAY['KR','US','GB','CA','AU','IN','JP','TW','HK','SG','BR']::text[])
);
CREATE INDEX trends_publication_policy_latest ON trends_publication_policy_events(blog_id,id DESC);
CREATE INDEX trends_auto_jobs_due ON publishing_jobs(available_at,scheduled_at,blog_id)
 WHERE publication_lane='trends_auto' AND NOT simulation_only
   AND adapter_type='blogger_live' AND status='queued';
CREATE TRIGGER trends_publication_policy_events_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON trends_publication_policy_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON trends_publication_policy_events TO woori_app;
GRANT USAGE,SELECT ON SEQUENCE trends_publication_policy_events_id_seq TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trends_publication_policy.migrated',
  '{"version":67,"enabled":false,"default_geographies":[],"existing_jobs_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(67);
