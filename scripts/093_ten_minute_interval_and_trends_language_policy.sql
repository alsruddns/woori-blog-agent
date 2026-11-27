-- P5-CODEX-159: set a 10-minute global minimum and add a Trends-specific
-- language/blog authorization without weakening the legacy auto flag.
ALTER TABLE automation_controls
  ALTER COLUMN global_publish_min_interval_minutes SET DEFAULT 10;
ALTER TABLE automation_controls
  DROP CONSTRAINT IF EXISTS automation_controls_global_publish_min_interval_minutes_check;
ALTER TABLE automation_controls
  ADD CONSTRAINT automation_controls_global_publish_min_interval_minutes_check
    CHECK (global_publish_min_interval_minutes BETWEEN 10 AND 1440);

ALTER TABLE publication_mode_settings
  ALTER COLUMN minimum_interval_minutes SET DEFAULT 10;
ALTER TABLE publication_mode_settings
  DROP CONSTRAINT IF EXISTS publication_mode_settings_minimum_interval_minutes_check;
ALTER TABLE publication_mode_settings
  ADD CONSTRAINT publication_mode_settings_minimum_interval_minutes_check
    CHECK (minimum_interval_minutes BETWEEN 10 AND 10080);

ALTER TABLE publishing_policies
  ADD COLUMN trends_auto_publish_allowed boolean NOT NULL DEFAULT false;

INSERT INTO audit_events(event_type,payload)
VALUES ('schema.p5_codex_159_interval_and_trends_language_policy.migrated',
  '{"version":93,"minimum_global_interval_minutes":10,"new_operational_values_changed":false,"existing_automatic_policy_flags_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(93);
