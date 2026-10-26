-- Durable, inspectable stage executions. A started row may be finalized once;
-- completed attempts remain available for comparison and are never deleted.
CREATE TABLE generation_stage_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 run_id uuid NOT NULL,
 profile_id uuid NOT NULL,
 worker_attempt integer NOT NULL CHECK(worker_attempt > 0),
 stage_attempt integer NOT NULL CHECK(stage_attempt > 0),
 sequence integer NOT NULL CHECK(sequence > 0),
 stage_name text NOT NULL CHECK(stage_name IN (
  'source_collection','evidence_extraction','evidence_validation','content_outline',
  'section_generation','localization','claim_verification','seo_quality','draft_persistence'
 )),
 status text NOT NULL CHECK(status IN ('running','succeeded','held','failed','cancelled')),
 model text NOT NULL,
 prompt_version text NOT NULL,
 input_snapshot jsonb NOT NULL,
 output_snapshot jsonb,
 source_ids text[] NOT NULL DEFAULT '{}',
 validation jsonb NOT NULL DEFAULT '{}',
 error_category text,
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 elapsed_ms integer CHECK(elapsed_ms IS NULL OR elapsed_ms >= 0),
 FOREIGN KEY(run_id,profile_id) REFERENCES generation_targets(run_id,profile_id),
 CHECK((status='running' AND finished_at IS NULL) OR (status<>'running' AND finished_at IS NOT NULL)),
 UNIQUE(run_id,profile_id,worker_attempt,sequence,stage_attempt)
);
CREATE INDEX generation_stage_runs_lookup ON generation_stage_runs(run_id,profile_id,sequence,stage_attempt);

CREATE FUNCTION finalize_generation_stage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.status <> 'running' OR NEW.status = 'running' OR
    (to_jsonb(OLD) - ARRAY['status','output_snapshot','validation','error_category','finished_at','elapsed_ms'])
    IS DISTINCT FROM
    (to_jsonb(NEW) - ARRAY['status','output_snapshot','validation','error_category','finished_at','elapsed_ms']) THEN
  RAISE EXCEPTION 'Generation stage attempts can only be finalized once';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER generation_stage_finalize BEFORE UPDATE ON generation_stage_runs
 FOR EACH ROW EXECUTE FUNCTION finalize_generation_stage();
CREATE TRIGGER generation_stage_immutable BEFORE DELETE OR TRUNCATE ON generation_stage_runs
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();

GRANT SELECT,INSERT ON generation_stage_runs TO woori_app;
GRANT UPDATE(status,output_snapshot,validation,error_category,finished_at,elapsed_ms)
 ON generation_stage_runs TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.generation_stages.migrated','{"version":14}');
INSERT INTO schema_migrations(version) VALUES(14);
