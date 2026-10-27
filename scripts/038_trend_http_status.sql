-- Preserve the actual provider response code; historical runs remain NULL and are not reconstructed.
ALTER TABLE trend_collection_runs
 ADD COLUMN http_status integer CHECK(http_status IS NULL OR http_status BETWEEN 100 AND 599);
INSERT INTO schema_migrations(version) VALUES(38);
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trend_http_status.migrated','{"version":38,"historical_status":"not_backfilled"}');
