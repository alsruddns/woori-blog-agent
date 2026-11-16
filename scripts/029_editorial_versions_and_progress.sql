-- Append-only editorial work state and revisions. These are not publication records.
CREATE TABLE article_review_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 evaluation_id uuid NOT NULL,
 content_version_id uuid NOT NULL,
 event_key text NOT NULL UNIQUE CHECK(length(event_key) BETWEEN 16 AND 128),
 reviewer_name text NOT NULL CHECK(length(reviewer_name) BETWEEN 2 AND 80),
 event_type text NOT NULL CHECK(event_type IN ('review_started','revision_saved')),
 payload jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX article_review_events_latest
 ON article_review_events(evaluation_id,content_version_id,created_at DESC,id DESC);
CREATE TRIGGER article_review_events_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON article_review_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();

CREATE TABLE article_editorial_versions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 evaluation_id uuid NOT NULL,
 base_content_version_id uuid NOT NULL,
 revision_number integer NOT NULL CHECK(revision_number > 0),
 idempotency_key text NOT NULL UNIQUE CHECK(length(idempotency_key) BETWEEN 16 AND 128),
 reviewer_name text NOT NULL CHECK(length(reviewer_name) BETWEEN 2 AND 80),
 reason text NOT NULL CHECK(length(reason) BETWEEN 10 AND 2000),
 title text NOT NULL CHECK(length(title) BETWEEN 1 AND 500),
 body text NOT NULL CHECK(length(body) BETWEEN 1 AND 50000),
 summary text NOT NULL CHECK(length(summary) BETWEEN 1 AND 3000),
 keywords text[] NOT NULL CHECK(cardinality(keywords) BETWEEN 1 AND 6),
 machine_checks jsonb NOT NULL,
 machine_passed boolean NOT NULL,
 quality_status text NOT NULL CHECK(quality_status IN ('quality_held','machine_checked_review_required')),
 body_sha256 char(64) NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(evaluation_id,base_content_version_id,revision_number)
);
CREATE TRIGGER article_editorial_versions_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON article_editorial_versions
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
ALTER TABLE article_human_reviews ADD COLUMN editorial_version_id uuid;
CREATE INDEX article_editorial_versions_latest
 ON article_editorial_versions(evaluation_id,base_content_version_id,created_at DESC,id DESC);
GRANT SELECT,INSERT ON article_review_events,article_editorial_versions TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.editorial_versions_and_progress.migrated',
   '{"version":29,"append_only":true,"publication_permission":false,"publish_ready_changes":false}');
INSERT INTO schema_migrations(version) VALUES(29);
