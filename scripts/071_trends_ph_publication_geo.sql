-- PH is already collected and explicitly mapped; preserve all historical policy events.
ALTER TABLE trends_publication_policy_events DROP CONSTRAINT trends_publication_policy_events_allowed_geos_check1;
ALTER TABLE trends_publication_policy_events ADD CONSTRAINT trends_publication_policy_events_allowed_geos_check1
 CHECK (allowed_geos <@ ARRAY['KR','US','GB','CA','AU','IN','JP','TW','HK','SG','BR','PH']::text[]);
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trends_ph_publication_geo.migrated','{"version":71,"existing_country_mappings_unchanged":true}');
INSERT INTO schema_migrations(version) VALUES(71);
