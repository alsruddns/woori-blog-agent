ALTER TABLE worker_heartbeats
  ADD COLUMN execution_mode text,
  ADD CONSTRAINT worker_heartbeats_execution_mode_check CHECK (
    execution_mode IS NULL OR execution_mode IN (
      'operations-mock-only', 'operations-confirmed-private-drafts',
      'operations-approved-live-publications', 'operations-scheduled-auto',
      'operations-manual-confirmed', 'operations-scheduled-auto-and-manual'
    )
  );

INSERT INTO audit_events(event_type,payload)
  VALUES ('schema.publication_worker_mode.migrated',
          '{"version":58,"historical_heartbeats_preserved":true}');
INSERT INTO schema_migrations(version) VALUES (58);
