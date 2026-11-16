-- Replace historical four-language checks with references to the active language registry.
-- API/import policy still requires the language row to be active; this migration
-- only removes a stale schema allowlist and preserves every existing import row.
ALTER TABLE external_content_imports
  DROP CONSTRAINT external_content_imports_language_code_check;
ALTER TABLE external_content_imports
  ADD CONSTRAINT external_content_imports_language_code_fkey
  FOREIGN KEY (language_code) REFERENCES languages(code) NOT VALID;
ALTER TABLE external_content_imports
  VALIDATE CONSTRAINT external_content_imports_language_code_fkey;

ALTER TABLE external_content_import_localization_events
  DROP CONSTRAINT external_content_import_localization_even_target_language_check;
ALTER TABLE external_content_import_localization_events
  ADD CONSTRAINT external_content_import_localization_events_target_language_fkey
  FOREIGN KEY (target_language) REFERENCES languages(code) NOT VALID;
ALTER TABLE external_content_import_localization_events
  VALIDATE CONSTRAINT external_content_import_localization_events_target_language_fkey;

INSERT INTO audit_events(event_type,payload) VALUES
  ('schema.registered_import_languages.migrated',
   '{"version":85,"registered_language_registry_enforced":true,"existing_imports_preserved":true,"publishing_authority_changed":false}');
INSERT INTO schema_migrations(version) VALUES(85);
