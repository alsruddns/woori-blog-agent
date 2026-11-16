-- Append-only editor metadata and optimistic concurrency for human manuscript revisions.
ALTER TABLE article_editorial_versions
 ADD COLUMN html_body text NOT NULL DEFAULT '',
 ADD COLUMN html_body_sha256 char(64) NOT NULL DEFAULT repeat('0',64),
 ADD COLUMN seo_description text NOT NULL DEFAULT '',
 ADD COLUMN blogger_labels text[] NOT NULL DEFAULT '{}',
 ADD COLUMN publication_mode text NOT NULL DEFAULT 'manual'
   CHECK(publication_mode IN ('draft','manual','scheduled')),
 ADD COLUMN planned_publish_at timestamptz,
 ADD COLUMN target_blog_id uuid REFERENCES blogger_blogs(id),
 ADD COLUMN base_editorial_version_id uuid REFERENCES article_editorial_versions(id),
 ADD CONSTRAINT article_editorial_html_body_length CHECK(length(html_body)<=100000),
 ADD CONSTRAINT article_editorial_seo_description_length CHECK(length(seo_description)<=3000),
 ADD CONSTRAINT article_editorial_labels_count CHECK(cardinality(blogger_labels)<=20),
 ADD CONSTRAINT article_editorial_schedule_requires_time CHECK(
   publication_mode <> 'scheduled' OR planned_publish_at IS NOT NULL
 );
CREATE INDEX article_editorial_versions_target_blog
 ON article_editorial_versions(target_blog_id,created_at DESC) WHERE target_blog_id IS NOT NULL;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.manuscript_editing_metadata.migrated',
   '{"version":30,"append_only":true,"html_allowlist":"server","optimistic_conflict_check":true,"publication_permission":false,"publish_ready_changes":false}');
INSERT INTO schema_migrations(version) VALUES(30);
