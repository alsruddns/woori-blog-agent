-- Explicit evaluation drafts must not falsely assert verified model-language quality.
ALTER TABLE generation_jobs ADD COLUMN evaluation_only boolean NOT NULL DEFAULT false;
INSERT INTO schema_migrations(version) VALUES(13);
INSERT INTO audit_events(event_type,payload) VALUES('schema.evaluation_jobs.migrated','{"version":13}');
