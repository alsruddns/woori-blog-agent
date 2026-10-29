-- Preserve the source label and add a nullable bucket lower bound. Historical
-- observations are immutable and are intentionally not backfilled.
ALTER TABLE trend_observations
  ADD COLUMN source_volume_lower_bound bigint,
  ADD COLUMN source_volume_period text,
  ADD CONSTRAINT trend_observations_volume_lower_bound_check
    CHECK (source_volume_lower_bound IS NULL OR source_volume_lower_bound >= 0);

INSERT INTO audit_events(event_type,payload)
  VALUES ('schema.trend_approx_traffic.migrated',
          '{"version":51,"raw_label_preserved":true,"period_nullable_until_verified":true,"historical_rows_preserved":true}');
INSERT INTO schema_migrations(version) VALUES (51);
