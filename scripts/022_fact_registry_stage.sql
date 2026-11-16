-- Add the append-only fact registry step to the existing immutable stage ledger.
ALTER TABLE generation_stage_runs DROP CONSTRAINT generation_stage_runs_stage_name_check;
ALTER TABLE generation_stage_runs ADD CONSTRAINT generation_stage_runs_stage_name_check
 CHECK(stage_name IN (
  'source_collection','evidence_extraction','fact_registry','evidence_validation','content_outline',
  'section_generation','localization','claim_verification','seo_quality','draft_persistence'
 ));
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.fact_registry_stage.migrated','{"version":22}');
INSERT INTO schema_migrations(version) VALUES(22);
