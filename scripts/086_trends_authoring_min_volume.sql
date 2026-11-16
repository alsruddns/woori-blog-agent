-- Minimum provider-reported approximate traffic lower bound for new Trends authoring.
-- Collection, editorial history, and existing authoring requests remain unchanged.
ALTER TABLE automation_controls
  ADD COLUMN trends_authoring_min_volume integer NOT NULL DEFAULT 5000
    CHECK (trends_authoring_min_volume BETWEEN 1 AND 1000000000);

INSERT INTO audit_events(event_type,payload)
VALUES ('schema.trends_authoring_min_volume.migrated',
  '{"version":86,"default":5000,"basis":"provider_approx_traffic_lower_bound","existing_requests_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(86);
