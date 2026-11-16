-- Bind an editorial update to an already verified Blogger post mapping.
ALTER TABLE article_editorial_versions
 ADD COLUMN existing_remote_post_id text,
 ADD CONSTRAINT article_editorial_remote_post_id_length
   CHECK(existing_remote_post_id IS NULL OR length(existing_remote_post_id) BETWEEN 1 AND 500);
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.editorial_existing_post_link.migrated',
   '{"version":31,"post_identity_from_publishing_records":true,"duplicate_insert_prevention":true,"live_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(31);
