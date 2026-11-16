-- Distinct external origin. Never relabel a Trends Codex job as a Desktop schedule.
ALTER TABLE external_content_imports DROP CONSTRAINT external_content_imports_generation_method_check;
ALTER TABLE external_content_imports ADD CONSTRAINT external_content_imports_generation_method_check
 CHECK(generation_method IN ('manual_codex_import','chatgpt_scheduled_export','other_external_export','codex_trends_export'));
ALTER TABLE codex_authoring_jobs ADD COLUMN trend_request_id uuid UNIQUE REFERENCES trend_generation_requests(id);
CREATE INDEX codex_trend_jobs ON codex_authoring_jobs(trend_request_id) WHERE trend_request_id IS NOT NULL;
INSERT INTO audit_events(event_type,payload) VALUES('schema.trend_codex_provenance.migrated',
 '{"version":63,"trends_origin_distinct":true,"live_publication_authority":false}');
INSERT INTO schema_migrations(version) VALUES(63);
