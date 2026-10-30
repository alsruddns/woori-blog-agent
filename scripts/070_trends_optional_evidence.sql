-- Preserve historical timestamps; do not fabricate a fact-check time for an unverified Trends draft.
ALTER TABLE external_content_imports ALTER COLUMN fact_checked_at DROP NOT NULL;
ALTER TABLE external_content_imports ADD CONSTRAINT non_trends_fact_check_timestamp_required
 CHECK (generation_method='codex_trends_export' OR fact_checked_at IS NOT NULL);
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trends_optional_evidence.migrated','{"version":70,"historical_claims_unchanged":true}');
INSERT INTO schema_migrations(version) VALUES(70);
