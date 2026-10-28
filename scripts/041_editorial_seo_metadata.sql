-- Version SEO metadata with each immutable human editorial revision.
ALTER TABLE article_editorial_versions
 ADD COLUMN seo_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 ADD CONSTRAINT article_editorial_seo_metadata_object
   CHECK (jsonb_typeof(seo_metadata) = 'object');

INSERT INTO audit_events(event_type,payload)
 VALUES('schema.editorial_seo_metadata.migrated',
   '{"version":41,"append_only":true,"search_console_connected":false,"publish_ready_changes":false}');
INSERT INTO schema_migrations(version) VALUES(41);
