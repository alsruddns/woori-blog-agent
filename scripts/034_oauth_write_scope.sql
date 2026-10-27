ALTER TABLE google_oauth_states
 ADD COLUMN requested_scopes text[] NOT NULL
 DEFAULT ARRAY['https://www.googleapis.com/auth/blogger.readonly']::text[];

INSERT INTO audit_events(event_type,payload)
VALUES ('schema.oauth_write_scope.migrated','{"version":34,"write_enabled":false}');
INSERT INTO schema_migrations(version) VALUES (34);
