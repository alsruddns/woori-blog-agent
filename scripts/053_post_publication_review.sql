-- Post-publication follow-up records. Rows are permitted only for remotely
-- verified LIVE publications; workflow edits are mirrored to append-only audit.
CREATE TABLE post_publication_reviews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 publishing_record_id uuid NOT NULL UNIQUE REFERENCES publishing_records(id),
 blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 content_version_id uuid NOT NULL REFERENCES content_versions(id),
 post_id text NOT NULL,
 import_id uuid REFERENCES external_content_imports(id),
 review_status text NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','in_progress','completed')),
 review_notes text NOT NULL DEFAULT '',
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE post_publication_review_items (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 review_id uuid NOT NULL REFERENCES post_publication_reviews(id),
 issue_type text NOT NULL CHECK (issue_type IN ('exchange_rate','source','number','date','translation','copyright','other')),
 severity text NOT NULL CHECK (severity IN ('low','medium','high')),
 description text NOT NULL CHECK (length(trim(description)) BETWEEN 1 AND 2000),
 resolved boolean NOT NULL DEFAULT false,
 resolved_at timestamptz,
 idempotency_key text NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 16 AND 128),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((resolved AND resolved_at IS NOT NULL) OR (NOT resolved AND resolved_at IS NULL))
);
CREATE INDEX post_publication_reviews_status_idx ON post_publication_reviews(review_status,updated_at DESC);
CREATE INDEX post_publication_review_items_open_idx ON post_publication_review_items(review_id,severity) WHERE NOT resolved;
CREATE FUNCTION require_verified_scheduled_publication_review() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM publishing_records p JOIN publishing_jobs j ON j.id=p.job_id
   WHERE p.id=NEW.publishing_record_id AND p.blog_id=NEW.blog_id
     AND p.content_version_id=NEW.content_version_id AND p.remote_post_id=NEW.post_id
     AND p.remote_status='LIVE' AND p.remote_verified_at IS NOT NULL
     AND j.publication_lane='scheduled_auto'
 ) THEN
   RAISE EXCEPTION 'post_publication_review_requires_verified_scheduled_live_record';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER verified_scheduled_review_only BEFORE INSERT ON post_publication_reviews
 FOR EACH ROW EXECUTE FUNCTION require_verified_scheduled_publication_review();
GRANT SELECT,INSERT,UPDATE ON post_publication_reviews,post_publication_review_items TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.post_publication_review.migrated',
  '{"version":53,"only_verified_live_records":true,"live_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(53);
