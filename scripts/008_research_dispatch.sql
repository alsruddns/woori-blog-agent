CREATE TABLE research_dispatches (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), schedule_id uuid NOT NULL REFERENCES research_schedules(id),
 keyword_id uuid NOT NULL REFERENCES keyword_candidates(id), occurrence timestamptz NOT NULL,
 dispatched_at timestamptz, error_category text, UNIQUE(schedule_id,keyword_id,occurrence));
GRANT SELECT,INSERT,UPDATE ON research_dispatches TO woori_app;
CREATE TRIGGER dispatch_audit AFTER INSERT OR UPDATE ON research_dispatches FOR EACH ROW EXECUTE FUNCTION audit_configuration();
INSERT INTO schema_migrations(version) VALUES(8);
INSERT INTO audit_events(event_type,payload) VALUES('schema.dispatch.migrated','{"version":8}');
