-- Append-only editorial feedback for isolated AI evaluation drafts.
-- These records do not change content versions or publication eligibility.
CREATE TABLE article_human_reviews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 evaluation_id uuid NOT NULL,
 content_version_id uuid NOT NULL,
 idempotency_key text NOT NULL UNIQUE CHECK(length(idempotency_key) BETWEEN 16 AND 128),
 reviewer_name text NOT NULL CHECK(length(reviewer_name) BETWEEN 2 AND 80),
 factual_accuracy text NOT NULL CHECK(factual_accuracy IN ('verified','issue_found','uncertain','not_assessed')),
 translation_naturalness text NOT NULL CHECK(translation_naturalness IN ('acceptable','issue_found','uncertain','not_assessed')),
 reader_value text NOT NULL CHECK(reader_value IN ('useful','insufficient','uncertain','not_assessed')),
 disposition text NOT NULL CHECK(disposition IN ('reviewed','revision_requested','rejected')),
 comments text NOT NULL CHECK(length(comments) BETWEEN 10 AND 2000),
 requested_changes text NOT NULL DEFAULT '' CHECK(length(requested_changes)<=2000),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(disposition <> 'revision_requested' OR length(requested_changes)>=10)
);
CREATE INDEX article_human_reviews_latest ON article_human_reviews(evaluation_id,created_at DESC,id DESC);
CREATE TRIGGER article_human_reviews_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON article_human_reviews
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON article_human_reviews TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.article_human_reviews.migrated','{"version":27,"append_only":true,"publication_approval":false}');
INSERT INTO schema_migrations(version) VALUES(27);
