-- Keep migrations immutable after first application; revise request recovery additively.
DO $$
DECLARE constraint_name text;
BEGIN
 FOR constraint_name IN
   SELECT conname FROM pg_constraint
   WHERE conrelid='localized_publication_requests'::regclass AND contype='u'
     AND pg_get_constraintdef(oid)='UNIQUE (source_group_id, target_language_code, target_blog_id)'
 LOOP
   EXECUTE format('ALTER TABLE localized_publication_requests DROP CONSTRAINT %I',constraint_name);
 END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS localized_publication_request_lineage
 ON localized_publication_requests(source_group_id,target_language_code,target_blog_id,created_at DESC);

CREATE OR REPLACE FUNCTION validate_localized_publication_request() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_language text; source_group uuid; version_localization uuid; mapped_language text;
BEGIN
 SELECT language_code,group_id INTO source_language,source_group
   FROM content_localizations WHERE id=NEW.source_localization_id;
 SELECT localization_id INTO version_localization FROM content_versions
   WHERE id=NEW.source_content_version_id;
 SELECT language_code INTO mapped_language FROM blogger_blogs
   WHERE id=NEW.target_blog_id AND active;
 IF source_language IS NULL OR source_language<>NEW.source_language_code
   OR source_group IS NULL OR source_group<>NEW.source_group_id
   OR version_localization IS NULL OR version_localization<>NEW.source_localization_id THEN
   RAISE EXCEPTION 'localized request source identity mismatch';
 END IF;
 IF mapped_language IS NULL OR mapped_language<>NEW.target_language_code THEN
   RAISE EXCEPTION 'localized request target blog language mismatch';
 END IF;
 RETURN NEW;
END; $$;

INSERT INTO audit_events(event_type,payload)
 VALUES('schema.localized_request_recovery.migrated',
   '{"version":44,"cancelled_requests_can_be_retried":true,"live_blogger_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(44);
