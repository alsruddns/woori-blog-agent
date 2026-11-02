-- P5-CODEX-108: keep collection and Blogger write cadences independent.
ALTER TABLE trend_collection_settings
  ALTER COLUMN interval_minutes SET DEFAULT 30;

-- The operator has already selected a 30-minute Trends cadence. Apply that
-- persisted choice now and clear the pending transition without touching history.
UPDATE trend_collection_settings
SET interval_minutes=30,pending_interval_minutes=NULL,effective_at=NULL,updated_at=clock_timestamp()
WHERE id=1;

ALTER TABLE automation_controls
  ADD COLUMN global_publish_min_interval_minutes integer NOT NULL DEFAULT 30
    CHECK (global_publish_min_interval_minutes BETWEEN 30 AND 1440);

UPDATE automation_controls SET revision=revision+1,updated_at=clock_timestamp() WHERE id=1;
INSERT INTO audit_events(event_type,payload)
VALUES ('publication.global_interval.configured',
        '{"trends_interval_minutes":30,"global_publish_min_interval_minutes":30,"historical_records_preserved":true}');
INSERT INTO audit_events(event_type,payload)
VALUES ('schema.p5_codex_108_intervals.migrated',
        '{"version":81,"trends_default_interval_minutes":30,"global_publish_min_interval_minutes":30}');
INSERT INTO schema_migrations(version) VALUES(81);

ALTER TABLE live_publication_attempts DROP CONSTRAINT live_publication_attempts_operation_check;
ALTER TABLE live_publication_attempts ADD CONSTRAINT live_publication_attempts_operation_check
  CHECK (operation IN ('create_draft','create_live','publish_draft'));
