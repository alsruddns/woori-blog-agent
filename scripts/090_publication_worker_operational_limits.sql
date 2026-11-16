-- P5-CODEX-134: permit the owner-approved global 15/100 settings and six-blog scope.
-- Operational values are changed separately through the audited admin APIs.
ALTER TABLE publication_mode_settings
  ALTER COLUMN daily_auto_limit SET DEFAULT 100,
  ALTER COLUMN minimum_interval_minutes SET DEFAULT 15;
ALTER TABLE publication_mode_settings
  DROP CONSTRAINT IF EXISTS publication_mode_settings_daily_auto_limit_check,
  DROP CONSTRAINT IF EXISTS publication_mode_settings_minimum_interval_minutes_check;
ALTER TABLE publication_mode_settings
  ADD CONSTRAINT publication_mode_settings_daily_auto_limit_check
    CHECK (daily_auto_limit BETWEEN 0 AND 100),
  ADD CONSTRAINT publication_mode_settings_minimum_interval_minutes_check
    CHECK (minimum_interval_minutes BETWEEN 15 AND 10080);

ALTER TABLE scheduled_publication_policy_events
  DROP CONSTRAINT IF EXISTS scheduled_publication_policy_events_check,
  DROP CONSTRAINT IF EXISTS scheduled_publication_policy_events_daily_limit_check;
ALTER TABLE scheduled_publication_policy_events
  ADD CONSTRAINT scheduled_publication_policy_events_check
    CHECK (action <> 'enabled' OR jsonb_array_length(approved_blog_ids) BETWEEN 1 AND 6),
  ADD CONSTRAINT scheduled_publication_policy_events_daily_limit_check
    CHECK (daily_limit BETWEEN 1 AND 100);

INSERT INTO audit_events(event_type,payload)
VALUES ('schema.p5_codex_134_publication_limits.migrated',
  '{"version":90,"mode_daily_limit_max":100,"minimum_interval_floor_minutes":15,"scheduled_scope_max_blogs":6,"scheduled_daily_limit_max":100,"operational_values_changed":false}');
INSERT INTO schema_migrations(version) VALUES(90);
