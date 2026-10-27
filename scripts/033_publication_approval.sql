-- Explicit human publication intent, tied to the exact immutable editorial body hash.
CREATE TABLE publication_approval_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 evaluation_id uuid NOT NULL,
 content_version_id uuid NOT NULL,
 editorial_version_id uuid REFERENCES article_editorial_versions(id),
 action text NOT NULL CHECK(action IN ('approved','revoked')),
 event_key text NOT NULL UNIQUE CHECK(length(event_key) BETWEEN 16 AND 128),
 actor text NOT NULL CHECK(length(actor) BETWEEN 2 AND 80),
 body_sha256 char(64) NOT NULL CHECK(body_sha256 ~ '^[0-9a-f]{64}$'),
 reason text NOT NULL CHECK(length(reason) BETWEEN 10 AND 2000),
 supersedes_event_id uuid REFERENCES publication_approval_events(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK((action='approved' AND supersedes_event_id IS NULL)
    OR (action='revoked' AND supersedes_event_id IS NOT NULL))
);
CREATE INDEX publication_approval_latest
 ON publication_approval_events(evaluation_id,content_version_id,created_at DESC,id DESC);
CREATE TRIGGER publication_approval_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON publication_approval_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON publication_approval_events TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.publication_approval.migrated',
   '{"version":33,"version_hash_bound":true,"append_only":true,"live_writes_enabled":false,"publish_ready_changes":false}');
INSERT INTO schema_migrations(version) VALUES(33);
