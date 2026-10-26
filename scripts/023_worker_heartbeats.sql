-- Mutable current heartbeat with append-only audit on status/error/process transitions.
CREATE TABLE worker_heartbeats (
 service_name text PRIMARY KEY CHECK(service_name='research_worker'),
 process_id integer NOT NULL CHECK(process_id>0),
 status text NOT NULL CHECK(status IN ('running','degraded')),
 last_error_category text,
 last_seen_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT,INSERT,UPDATE ON worker_heartbeats TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.worker_heartbeats.migrated','{"version":23}');
INSERT INTO schema_migrations(version) VALUES(23);
