-- Persist operator publication preferences without granting live publication.
CREATE TABLE publication_mode_settings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 scope_type text NOT NULL CHECK (scope_type IN ('global','language','blog')),
 scope_key text NOT NULL,
 configured_mode text NOT NULL DEFAULT 'manual'
   CHECK (configured_mode IN ('manual','auto')),
 daily_auto_limit integer NOT NULL DEFAULT 1 CHECK (daily_auto_limit BETWEEN 0 AND 3),
 minimum_interval_minutes integer NOT NULL DEFAULT 1440
   CHECK (minimum_interval_minutes BETWEEN 60 AND 10080),
 allowed_start_hour smallint NOT NULL DEFAULT 9 CHECK (allowed_start_hour BETWEEN 0 AND 23),
 allowed_end_hour smallint NOT NULL DEFAULT 17 CHECK (allowed_end_hour BETWEEN 0 AND 23),
 timezone text NOT NULL DEFAULT 'Asia/Seoul' CHECK (length(timezone) BETWEEN 1 AND 100),
 allowed_categories text[] NOT NULL DEFAULT '{}',
 excluded_topics text[] NOT NULL DEFAULT '{}',
 max_source_age_hours integer NOT NULL DEFAULT 24 CHECK (max_source_age_hours BETWEEN 1 AND 720),
 retry_limit smallint NOT NULL DEFAULT 0 CHECK (retry_limit BETWEEN 0 AND 2),
 emergency_stopped boolean NOT NULL DEFAULT false,
 operations_auto_approved boolean NOT NULL DEFAULT false CHECK (NOT operations_auto_approved),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(scope_type,scope_key),
 CHECK ((scope_type='global' AND scope_key='') OR
        (scope_type='language' AND length(scope_key) BETWEEN 2 AND 35) OR
        (scope_type='blog' AND scope_key ~ '^[0-9a-fA-F-]{36}$')),
 CHECK ((scope_type='global') OR NOT emergency_stopped)
);
CREATE TRIGGER publication_mode_settings_audit
 AFTER INSERT OR UPDATE ON publication_mode_settings
 FOR EACH ROW EXECUTE FUNCTION audit_configuration();
CREATE TRIGGER publication_mode_settings_identity
 BEFORE UPDATE ON publication_mode_settings
 FOR EACH ROW EXECUTE FUNCTION protect_identity('id','scope_type','scope_key','operations_auto_approved');
GRANT SELECT,INSERT,UPDATE ON publication_mode_settings TO woori_app;
INSERT INTO publication_mode_settings(scope_type,scope_key,configured_mode,emergency_stopped)
 VALUES('global','','manual',false);
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.publication_modes.migrated',
   '{"version":42,"default_mode":"manual","live_auto_approved":false,"live_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(42);
