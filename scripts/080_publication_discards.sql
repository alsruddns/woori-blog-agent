-- A group/blog scope keeps later Content Versions held until an operator restores it.
CREATE TABLE manuscript_discards (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 group_id uuid NOT NULL REFERENCES content_groups(id),
 blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 content_version_id uuid NOT NULL REFERENCES content_versions(id),
 status text NOT NULL CHECK (status IN ('discarded','restored')),
 previous_view text NOT NULL CHECK (previous_view IN ('queue','review','held','auto_failure')),
 reason text NOT NULL,
 actor text NOT NULL,
 discarded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 restored_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(group_id,blog_id)
);
CREATE INDEX manuscript_discards_active ON manuscript_discards(blog_id,group_id)
 WHERE status='discarded';
GRANT SELECT,INSERT,UPDATE ON manuscript_discards TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES('schema.publication_discards.migrated',
 '{"version":80,"historical_versions_jobs_and_publications_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(80);
