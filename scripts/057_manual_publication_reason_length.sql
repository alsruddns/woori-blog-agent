-- Align the append-only manual publication approval reason constraint with the
-- API's three-character minimum. Existing approval rows remain unchanged.
ALTER TABLE manual_publication_approval_events
  DROP CONSTRAINT manual_publication_approval_events_reason_check;
ALTER TABLE manual_publication_approval_events
  ADD CONSTRAINT manual_publication_approval_events_reason_min_3_check
  CHECK (length(trim(reason)) BETWEEN 3 AND 2000);

INSERT INTO audit_events(event_type,payload)
VALUES ('schema.manual_publication_reason_length.migrated',
        '{"version":57,"reason_min_length":3,"existing_approval_rows_changed":false}');
INSERT INTO schema_migrations(version) VALUES (57);
