-- Allow scheduled-auto review items to be recorded before Blogger publication,
-- then bind them to the verified remote post without replacing prior records.
ALTER TABLE post_publication_reviews
  ALTER COLUMN publishing_record_id DROP NOT NULL,
  ALTER COLUMN post_id DROP NOT NULL,
  ADD COLUMN publishing_job_id uuid REFERENCES publishing_jobs(id);
CREATE UNIQUE INDEX post_publication_reviews_job_uq
  ON post_publication_reviews(publishing_job_id) WHERE publishing_job_id IS NOT NULL;

CREATE OR REPLACE FUNCTION require_verified_scheduled_publication_review()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  job_lane text;
  job_status text;
BEGIN
  IF NEW.publishing_record_id IS NOT NULL THEN
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
  END IF;

  IF NEW.post_id IS NOT NULL OR NEW.publishing_job_id IS NULL OR NOT EXISTS (
    SELECT 1 FROM publishing_jobs j
    JOIN external_content_import_content_links l ON l.content_version_id=j.content_version_id
    JOIN external_content_imports i ON i.id=l.import_id
    JOIN blogger_blogs b ON b.id=j.blog_id
    JOIN LATERAL (
      SELECT action,approved_blog_ids FROM scheduled_publication_policy_events
      ORDER BY id DESC LIMIT 1
    ) policy ON policy.action='enabled' AND policy.approved_blog_ids ? b.id::text
    WHERE j.id=NEW.publishing_job_id AND j.blog_id=NEW.blog_id
      AND j.content_version_id=NEW.content_version_id AND j.publication_lane='scheduled_auto'
      AND j.simulation_only=false AND j.status IN ('queued','running')
      AND i.id=NEW.import_id AND i.generation_method='chatgpt_scheduled_export'
  ) THEN
    RAISE EXCEPTION 'prepublication_review_requires_active_scheduled_job';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER verified_scheduled_review_only ON post_publication_reviews;
CREATE TRIGGER verified_scheduled_review_only BEFORE INSERT OR UPDATE ON post_publication_reviews
  FOR EACH ROW EXECUTE FUNCTION require_verified_scheduled_publication_review();

GRANT SELECT,INSERT,UPDATE ON post_publication_reviews TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.scheduled_prepublication_review.migrated',
  '{"version":55,"scheduled_job_bound_prepublication_items":true,"existing_review_data_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(55);
