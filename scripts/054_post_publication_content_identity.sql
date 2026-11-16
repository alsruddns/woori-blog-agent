-- Preserve the source-system content identifier alongside the immutable
-- content-version and import references in follow-up records.
ALTER TABLE post_publication_reviews ADD COLUMN content_id text;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.post_publication_content_identity.migrated',
  '{"version":54,"content_versions_and_import_links_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(54);
