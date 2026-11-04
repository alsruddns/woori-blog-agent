-- A neutral research category lets high-interest observations enter research
-- even when deterministic topic classification cannot assign a narrower lane.
-- This does not approve a generated article or alter publication eligibility.
INSERT INTO categories(slug) VALUES ('general-news') ON CONFLICT(slug) DO NOTHING;
INSERT INTO audit_events(event_type,payload) VALUES
  ('schema.trends_general_news_category.migrated',
   '{"version":88,"purpose":"volume-priority-research-handoff","publication_authorized":false}');
INSERT INTO schema_migrations(version) VALUES (88);
