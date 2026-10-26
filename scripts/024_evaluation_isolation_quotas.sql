-- Keep evaluation workload separately accounted and disabled until DB isolation is confirmed.
ALTER TABLE generation_settings
 ADD COLUMN evaluation_daily_limit integer NOT NULL DEFAULT 2
 CHECK(evaluation_daily_limit BETWEEN 0 AND 50);
ALTER TABLE pipeline_controls
 ADD COLUMN evaluation_isolated boolean NOT NULL DEFAULT false;
ALTER TABLE worker_heartbeats DROP CONSTRAINT worker_heartbeats_service_name_check;
ALTER TABLE worker_heartbeats ADD CONSTRAINT worker_heartbeats_service_name_check
 CHECK(service_name IN ('research_worker','evaluation_worker'));
ALTER TABLE worker_heartbeats DROP CONSTRAINT worker_heartbeats_status_check;
ALTER TABLE worker_heartbeats ADD CONSTRAINT worker_heartbeats_status_check
 CHECK(status IN ('running','degraded','stopped'));
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.evaluation_isolation.migrated','{"version":24,"evaluation_isolated_default":false}');
INSERT INTO schema_migrations(version) VALUES(24);
