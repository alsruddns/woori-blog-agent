-- Runtime may append quality results, never change existing ones.
GRANT INSERT ON seo_audits TO woori_app;
INSERT INTO schema_migrations(version) VALUES(9);
INSERT INTO audit_events(event_type,payload) VALUES('schema.pipeline_permissions.migrated','{"version":9}');
