-- Preserve language-specific SEO keyword candidates with each immutable evaluation.
ALTER TABLE article_quality_evaluations
 ADD COLUMN keywords text[] NOT NULL DEFAULT '{}';
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.article_keywords.migrated','{"version":20}');
INSERT INTO schema_migrations(version) VALUES(20);
