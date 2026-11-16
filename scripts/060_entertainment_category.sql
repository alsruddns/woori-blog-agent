-- Additive only: keep legacy k-pop and all historical references unchanged.
INSERT INTO categories(slug) VALUES ('entertainment') ON CONFLICT(slug) DO NOTHING;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.editorial_entertainment.migrated','{"version":60,"task_id":"P5-CODEX-077","category":"entertainment","historical_categories_preserved":true}');
INSERT INTO schema_migrations(version) VALUES (60);
