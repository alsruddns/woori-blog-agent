ALTER TABLE research_sources ADD COLUMN revision integer NOT NULL DEFAULT 1 CHECK(revision>0);
ALTER TABLE research_sources DROP CONSTRAINT research_sources_keyword_id_url_key;
ALTER TABLE research_sources ADD UNIQUE(keyword_id,url,revision);
INSERT INTO schema_migrations(version) VALUES(12);
INSERT INTO audit_events(event_type,payload) VALUES('schema.source_revisions.migrated','{"version":12}');
