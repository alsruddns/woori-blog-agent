CREATE TABLE trend_collection_settings (
 id integer PRIMARY KEY DEFAULT 1 CHECK(id=1),
 enabled boolean NOT NULL DEFAULT true,
 interval_minutes integer NOT NULL DEFAULT 10 CHECK(interval_minutes IN (5,10,15,20,30,60)),
 pending_interval_minutes integer CHECK(pending_interval_minutes IN (5,10,15,20,30,60)),
 effective_at timestamptz,
 backoff_until timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO trend_collection_settings(id) VALUES(1);
GRANT SELECT,UPDATE ON trend_collection_settings TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES ('schema.trend_collection_settings.migrated',
 '{"version":64,"default_interval_minutes":10,"prior_observations_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(64);
