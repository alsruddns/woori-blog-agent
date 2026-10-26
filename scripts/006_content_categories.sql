GRANT INSERT ON localization_categories TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES('schema.content.migrated','{"version":6}');
INSERT INTO schema_migrations(version) VALUES(6);
