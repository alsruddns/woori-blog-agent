ALTER TABLE publication_mode_settings DROP CONSTRAINT publication_mode_settings_configured_mode_check;
ALTER TABLE publication_mode_settings ADD CONSTRAINT publication_mode_settings_configured_mode_check
 CHECK(configured_mode IN ('authoring_only','manual','auto'));
ALTER TABLE publication_mode_settings ALTER COLUMN configured_mode SET DEFAULT 'authoring_only';
INSERT INTO audit_events(event_type,payload)
 SELECT 'publication.authoring_only.activated',jsonb_build_object(
 'task','P5-CODEX-097','previous_mode',configured_mode,'previous_emergency_stop',emergency_stopped,
 'new_mode','authoring_only','reason','Google Blogger access restriction; all API writes suspended',
 'jobs_preserved',true,'remote_write_performed',false)
 FROM publication_mode_settings WHERE scope_type='global' AND scope_key='';
UPDATE publication_mode_settings SET configured_mode='authoring_only',emergency_stopped=true,updated_at=now()
 WHERE scope_type='global' AND scope_key='';
INSERT INTO schema_migrations(version) VALUES(74);
