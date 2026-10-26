-- Append-only quality and generation-mode experiment history.
CREATE TABLE research_experiment_evaluations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 experiment_id uuid NOT NULL,
 run_id uuid NOT NULL REFERENCES job_runs(id),
 content_version_id uuid NOT NULL REFERENCES content_versions(id),
 language text NOT NULL REFERENCES languages(code),
 variant text NOT NULL CHECK(variant IN ('existing_ai','evidence_template')),
 output_snapshot jsonb NOT NULL,
 metrics jsonb NOT NULL,
 checks jsonb NOT NULL,
 mechanical_gate_passed boolean NOT NULL,
 human_review_required boolean NOT NULL DEFAULT true,
 publish_ready boolean NOT NULL DEFAULT false CHECK(NOT publish_ready),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX research_experiment_lookup
 ON research_experiment_evaluations(experiment_id,language,variant,created_at DESC);
CREATE TRIGGER research_experiment_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON research_experiment_evaluations
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON research_experiment_evaluations TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.research_experiment_evaluations.migrated','{"version":15}');
INSERT INTO schema_migrations(version) VALUES(15);
