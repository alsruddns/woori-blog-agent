-- Add the already configured DE/VN authoring regions to the existing Trends
-- publication policy contract. No policy event or publication job is created.
ALTER TABLE trends_publication_policy_events
  DROP CONSTRAINT trends_publication_policy_events_allowed_geos_check1;
ALTER TABLE trends_publication_policy_events
  ADD CONSTRAINT trends_publication_policy_events_allowed_geos_check1
  CHECK (allowed_geos <@ ARRAY['KR','US','GB','CA','AU','IN','JP','TW','HK','SG','BR','PH','DE','VN']::text[]);

INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trends_de_vn_publication_geos.migrated',
  '{"version":92,"added_geos":["DE","VN"],"existing_policy_events_preserved":true,"publication_jobs_created":false}');
INSERT INTO schema_migrations(version) VALUES(92);
