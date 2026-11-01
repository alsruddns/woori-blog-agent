ALTER TABLE automation_controls
 ADD COLUMN trends_auto_publishing_enabled boolean NOT NULL DEFAULT false,
 ADD COLUMN scheduled_auto_publishing_enabled boolean NOT NULL DEFAULT false,
 ADD COLUMN trends_auto_epoch uuid NOT NULL DEFAULT gen_random_uuid(),
 ADD COLUMN scheduled_auto_epoch uuid NOT NULL DEFAULT gen_random_uuid(),
 ADD COLUMN trends_auto_enabled_at timestamptz,
 ADD COLUMN scheduled_auto_enabled_at timestamptz;
-- Old automatic grants acquire no origin authority. Manual grants retain their semantics.
ALTER TABLE automation_publication_grants
 ADD COLUMN manuscript_origin text NOT NULL DEFAULT 'unknown'
   CHECK(manuscript_origin IN ('google_trends','scheduled','manual','unknown')),
 ADD COLUMN source_epoch uuid,
 ADD COLUMN origin_import_id uuid REFERENCES external_content_imports(id),
 ADD COLUMN origin_content_version_id uuid REFERENCES content_versions(id);
UPDATE automation_controls SET revision=revision+1,updated_at=clock_timestamp() WHERE id=1;
INSERT INTO audit_events(event_type,payload) VALUES('schema.origin_publication_controls.migrated',
 '{"version":78,"trends_auto_publishing_enabled":false,"scheduled_auto_publishing_enabled":false,"historical_grants_authorized":false}');
INSERT INTO schema_migrations(version) VALUES(78);
