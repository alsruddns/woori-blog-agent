-- P5-CODEX-136 follow-up: permit a separately audited, exact-scope LIVE approval.
-- Defaults remain fail-closed; this migration does not enable publishing.
ALTER TABLE publication_mode_settings
  DROP CONSTRAINT IF EXISTS publication_mode_settings_blogger_write_mode_check,
  DROP CONSTRAINT IF EXISTS publication_mode_settings_operations_auto_approved_check;

ALTER TABLE publication_mode_settings
  ADD CONSTRAINT publication_mode_settings_blogger_write_mode_check
    CHECK (blogger_write_mode IN ('manual_only','public_write_approved')),
  ADD CONSTRAINT publication_mode_settings_operations_auto_approved_check
    CHECK (operations_auto_approved IN (true,false));

DROP TRIGGER IF EXISTS publication_mode_settings_identity ON publication_mode_settings;
CREATE TRIGGER publication_mode_settings_identity
 BEFORE UPDATE ON publication_mode_settings
 FOR EACH ROW EXECUTE FUNCTION protect_identity('id','scope_type','scope_key');

INSERT INTO audit_events(event_type,payload)
VALUES ('schema.p5_codex_136_scoped_live_approval.migrated',
  '{"version":91,"public_write_default":"manual_only","operations_auto_approved_default":false,"scope_enforced_by_audited_admin_path":true,"existing_jobs_unchanged":true}');
INSERT INTO schema_migrations(version) VALUES (91);
