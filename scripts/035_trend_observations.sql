-- Phase 5 trend collection: source observations are distinct from evidence sources.
CREATE TABLE trend_collection_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 provider text NOT NULL CHECK(provider='google_trends_rss'),
 geo text NOT NULL CHECK(geo IN ('KR','US','JP','TW','HK','SG')),
 status text NOT NULL CHECK(status IN ('succeeded','failed','blocked')),
 source_updated_at timestamptz,
 response_sha256 text CHECK(response_sha256 IS NULL OR response_sha256 ~ '^[a-f0-9]{64}$'),
 item_count integer NOT NULL DEFAULT 0 CHECK(item_count>=0),
 failure_category text,
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE trend_observations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 run_id uuid NOT NULL REFERENCES trend_collection_runs(id),
 geo text NOT NULL CHECK(geo IN ('KR','US','JP','TW','HK','SG')),
 platform text NOT NULL CHECK(platform='google_trends'),
 query text NOT NULL CHECK(length(query) BETWEEN 1 AND 300),
 source_rank integer CHECK(source_rank IS NULL OR source_rank>0),
 source_volume_label text,
 trend_started_at timestamptz,
 source_updated_at timestamptz,
 collected_at timestamptz NOT NULL DEFAULT now(),
 related_terms text[] NOT NULL DEFAULT '{}',
 source_url text NOT NULL CHECK(source_url LIKE 'https://trends.google.com/%'),
 response_sha256 text NOT NULL CHECK(response_sha256 ~ '^[a-f0-9]{64}$'),
 UNIQUE(run_id,query)
);
CREATE TRIGGER trend_run_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_collection_runs
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER trend_observation_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_observations
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON trend_collection_runs,trend_observations TO woori_app;
INSERT INTO schema_migrations(version) VALUES(35);
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trend_observations.migrated','{"version":35,"provider":"google_trends_rss","rank_is_source_only":true}');
