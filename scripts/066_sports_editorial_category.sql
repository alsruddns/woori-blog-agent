-- Additive taxonomy entry required for sports Trends candidates and imports.
-- Existing categories, content, and editorial history remain unchanged.
INSERT INTO categories(slug) VALUES ('sports') ON CONFLICT(slug) DO NOTHING;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.editorial_sports.migrated','{"version":66,"task_id":"P5-CODEX-088","category":"sports","historical_categories_preserved":true}');
INSERT INTO schema_migrations(version) VALUES (66);
