-- P5-CODEX-110-OPS: publish cadence and one KST LIVE ceiling for all four blogs.
ALTER TABLE automation_controls
  ALTER COLUMN global_publish_min_interval_minutes SET DEFAULT 15;

ALTER TABLE automation_controls
  DROP CONSTRAINT IF EXISTS automation_controls_global_publish_min_interval_minutes_check;
ALTER TABLE automation_controls
  ADD CONSTRAINT automation_controls_global_publish_min_interval_minutes_check
  CHECK (global_publish_min_interval_minutes BETWEEN 15 AND 1440);

ALTER TABLE automation_controls
  ADD COLUMN global_daily_live_publish_limit integer NOT NULL DEFAULT 100
  CHECK (global_daily_live_publish_limit BETWEEN 1 AND 1000);

WITH previous AS MATERIALIZED (
  SELECT revision,global_publish_min_interval_minutes FROM automation_controls WHERE id=1
), updated AS (
  UPDATE automation_controls c SET
    global_publish_min_interval_minutes=15,
    global_daily_live_publish_limit=100,
    revision=c.revision+1,
    updated_at=clock_timestamp()
  WHERE c.id=1
  RETURNING c.revision,c.global_publish_min_interval_minutes,c.global_daily_live_publish_limit
)
INSERT INTO audit_events(event_type,payload)
SELECT 'automation.controls.changed',jsonb_build_object(
  'actor','P5-CODEX-110-OPS migration',
  'reason','Apply the requested 15-minute global write interval and 100-per-KST-day LIVE ceiling.',
  'source','schema_migration_082',
  'revision',updated.revision,
  'changes',jsonb_build_array(
    jsonb_build_object('key','global_publish_min_interval_minutes',
      'before',previous.global_publish_min_interval_minutes,'after',updated.global_publish_min_interval_minutes),
    jsonb_build_object('key','global_daily_live_publish_limit',
      'before',null,'after',updated.global_daily_live_publish_limit)
  )
) FROM previous CROSS JOIN updated;

INSERT INTO audit_events(event_type,payload)
VALUES ('schema.p5_codex_110_ops.migrated',
        '{"version":82,"global_publish_min_interval_minutes":15,"global_daily_live_publish_limit":100,"timezone":"Asia/Seoul"}');
INSERT INTO schema_migrations(version) VALUES(82);
