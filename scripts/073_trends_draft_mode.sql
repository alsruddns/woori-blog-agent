ALTER TABLE trends_publication_policy_events ADD COLUMN publication_mode text NOT NULL DEFAULT 'draft'
 CHECK(publication_mode IN ('draft','publish'));
ALTER TABLE publishing_jobs ADD COLUMN publication_mode text NOT NULL DEFAULT 'publish'
 CHECK(publication_mode IN ('draft','publish')),
 ADD COLUMN trends_policy_event_id bigint REFERENCES trends_publication_policy_events(id);
ALTER TABLE publishing_jobs DROP CONSTRAINT publishing_jobs_publication_state_check;
ALTER TABLE publishing_jobs ADD CONSTRAINT publishing_jobs_publication_state_check CHECK(publication_state IN
 ('draft','quality_held','machine_checked','human_review_pending','human_review_rejected','human_review_approved',
 'publication_blocked','publication_queued','publishing','published','publication_failed','cancelled','draft_saved'));
CREATE FUNCTION protect_publication_mode_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.publication_mode IS DISTINCT FROM OLD.publication_mode OR NEW.trends_policy_event_id IS DISTINCT FROM OLD.trends_policy_event_id THEN
  RAISE EXCEPTION 'publication_mode_snapshot_immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER publication_mode_snapshot_immutable BEFORE UPDATE ON publishing_jobs
 FOR EACH ROW EXECUTE FUNCTION protect_publication_mode_snapshot();
CREATE TABLE blogger_draft_receipts (
 job_id uuid PRIMARY KEY REFERENCES publishing_jobs(id), blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 content_version_id uuid NOT NULL REFERENCES content_versions(id), remote_post_id text NOT NULL,
 remote_status text NOT NULL CHECK(remote_status='DRAFT'), verified_at timestamptz NOT NULL DEFAULT now(),
 review_status text NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending','changes_required','completed')),
 UNIQUE(blog_id,content_version_id), UNIQUE(blog_id,remote_post_id)
);
GRANT SELECT,INSERT ON blogger_draft_receipts TO woori_app;
-- Preserve an existing, explicitly consented public policy by appending its mode snapshot.
INSERT INTO trends_publication_policy_events(blog_id,enabled,allowed_geos,daily_limit,actor_label,reason,idempotency_key,publication_mode)
SELECT p.blog_id,true,p.allowed_geos,p.daily_limit,'schema_073',
 'Preserve previously explicitly approved Trends public publication mode', 'schema-073-preserve-'||p.id,'publish'
FROM (SELECT DISTINCT ON(blog_id) * FROM trends_publication_policy_events ORDER BY blog_id,id DESC) p
WHERE p.enabled AND EXISTS(SELECT 1 FROM audit_events a WHERE a.blog_id=p.blog_id
 AND a.event_type='publication.trends_public_write.approved' AND a.created_at<=p.created_at);
INSERT INTO audit_events(event_type,payload) VALUES ('schema.trends_draft_mode.migrated','{"version":73,"default_mode":"draft","existing_jobs_preserved":true}');
INSERT INTO schema_migrations(version) VALUES(73);
