ALTER TABLE worker_heartbeats DROP CONSTRAINT worker_heartbeats_execution_mode_check;
ALTER TABLE worker_heartbeats ADD CONSTRAINT worker_heartbeats_execution_mode_check CHECK (
  execution_mode IS NULL OR execution_mode IN (
    'operations-mock-only', 'operations-confirmed-private-drafts',
    'operations-approved-live-publications', 'operations-scheduled-auto',
    'operations-manual-confirmed', 'operations-scheduled-auto-and-manual',
    'operations-scheduled-auto-and-manual-and-trends'
  )
);
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trends_worker_heartbeat_mode.migrated',
  '{"version":68,"prior_heartbeats_preserved":true,"publications_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(68);
