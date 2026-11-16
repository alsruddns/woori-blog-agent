-- Grant only insertion of verified records; append-only trigger stays intact.
GRANT INSERT ON publishing_records TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.publication_record_insert.migrated','{"version":59,"append_only_preserved":true}');
INSERT INTO schema_migrations(version) VALUES (59);
