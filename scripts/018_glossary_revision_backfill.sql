-- Preserve existing terms as an initial, explicitly unapproved glossary revision.
INSERT INTO glossary_entry_revisions(entry_id,revision,profile_id,source_term,source_language,
 target_language,localized_term,official_translation,translation_source,approved,notes)
SELECT g.id,1,g.profile_id,g.source_term,g.source_language,g.target_language,g.localized_term,
 g.official_translation,g.translation_source,g.approved,g.notes
FROM glossary_entries g
WHERE NOT EXISTS(SELECT 1 FROM glossary_entry_revisions r WHERE r.entry_id=g.id);
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.glossary_revision_backfill.migrated','{"version":18}');
INSERT INTO schema_migrations(version) VALUES(18);
