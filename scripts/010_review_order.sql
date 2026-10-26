-- UUID order cannot determine the latest review when timestamps tie.
ALTER TABLE source_reviews ADD COLUMN review_sequence bigint GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX source_review_order ON source_reviews(review_sequence);
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO woori_app;
INSERT INTO schema_migrations(version) VALUES(10);
INSERT INTO audit_events(event_type,payload) VALUES('schema.review_order.migrated','{"version":10}');
