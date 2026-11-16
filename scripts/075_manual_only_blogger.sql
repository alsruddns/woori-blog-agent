ALTER TABLE publication_mode_settings ADD COLUMN blogger_write_mode text NOT NULL DEFAULT 'manual_only'
 CHECK(blogger_write_mode='manual_only'),
 ADD COLUMN blogger_api_restricted boolean NOT NULL DEFAULT true;
UPDATE publication_mode_settings SET configured_mode='manual',updated_at=now()
 WHERE scope_type='global' AND scope_key='';
INSERT INTO audit_events(event_type,payload) VALUES ('publication.manual_only.activated',
 '{"task":"P5-CODEX-097","automatic_writes":false,"google_restriction_active":true,"existing_jobs_preserved":true,"manual_default":"publish"}');
INSERT INTO schema_migrations(version) VALUES(75);
