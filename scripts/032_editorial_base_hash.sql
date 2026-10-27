-- Persist the content hash used for optimistic editorial conflict detection.
ALTER TABLE article_editorial_versions
 ADD COLUMN base_body_sha256 char(64),
 ADD CONSTRAINT article_editorial_base_body_sha256_format
   CHECK(base_body_sha256 IS NULL OR base_body_sha256 ~ '^[0-9a-f]{64}$');
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.editorial_base_hash.migrated',
   '{"version":32,"optimistic_conflict_hash":true,"live_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(32);
