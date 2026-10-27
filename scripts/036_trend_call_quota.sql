-- Durable application quota reservation, separate from the per-process HTTP cap.
CREATE TABLE trend_collection_attempts (
 id uuid PRIMARY KEY,
 provider text NOT NULL CHECK(provider='google_trends_rss'),
 geo text NOT NULL CHECK(geo IN ('KR','US','JP','TW','HK','SG')),
 attempted_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trend_attempt_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON trend_collection_attempts
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON trend_collection_attempts TO woori_app;
INSERT INTO schema_migrations(version) VALUES(36);
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trend_quota.migrated','{"version":36,"hourly_cap":12,"reservation":"append_only"}');
