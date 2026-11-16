-- Distinguish a fully captured, machine-checked evidence package from one that
-- has passed the existing human independence and editorial gates.
ALTER TABLE trend_research_packages
  DROP CONSTRAINT trend_research_packages_status_check;
ALTER TABLE trend_research_packages
  ADD CONSTRAINT trend_research_packages_status_check
  CHECK (status IN (
    'insufficient_evidence',
    'evidence_collected_pending_human_review',
    'evidence_ready_for_human_review'
  ));
INSERT INTO schema_migrations(version) VALUES(40);
INSERT INTO audit_events(event_type,payload) VALUES
  ('schema.research_package_review_state.migrated',
   '{"version":40,"publish_ready_unchanged":true,"human_review_required":true}');
