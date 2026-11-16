-- Trends publication has no daily or collection-round volume ceiling.
-- Keep legacy event values intact; NULL on new events means unlimited.
ALTER TABLE trends_publication_policy_events
  ALTER COLUMN daily_limit DROP NOT NULL;
ALTER TABLE trends_publication_policy_events
  DROP CONSTRAINT trends_publication_policy_events_daily_limit_check;
ALTER TABLE trends_publication_policy_events
  ADD CONSTRAINT trends_publication_policy_events_daily_limit_check
  CHECK (daily_limit IS NULL OR daily_limit BETWEEN 1 AND 10);

INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trends_unlimited_publication.migrated',
  '{"version":69,"new_policy_default":"unlimited","historical_events_preserved":true,"publication_spacing_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(69);
