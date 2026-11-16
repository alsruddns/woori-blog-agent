-- Expand the existing Google Trends RSS allowlist without rewriting observations.
ALTER TABLE trend_collection_runs DROP CONSTRAINT trend_collection_runs_geo_check;
ALTER TABLE trend_collection_runs ADD CONSTRAINT trend_collection_runs_geo_check
  CHECK (geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH'));
ALTER TABLE trend_collection_attempts DROP CONSTRAINT trend_collection_attempts_geo_check;
ALTER TABLE trend_collection_attempts ADD CONSTRAINT trend_collection_attempts_geo_check
  CHECK (geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH'));
ALTER TABLE trend_observations DROP CONSTRAINT trend_observations_geo_check;
ALTER TABLE trend_observations ADD CONSTRAINT trend_observations_geo_check
  CHECK (geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH'));
ALTER TABLE trend_topics DROP CONSTRAINT trend_topics_representative_geo_check;
ALTER TABLE trend_topics ADD CONSTRAINT trend_topics_representative_geo_check
  CHECK (representative_geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH'));
INSERT INTO audit_events(event_type,payload)
  VALUES ('schema.trends_eleven_geographies.migrated',
          '{"version":50,"geographies":["KR","US","JP","TW","HK","SG","GB","CA","AU","IN","PH"],"historical_rows_preserved":true}');
INSERT INTO schema_migrations(version) VALUES (50);
