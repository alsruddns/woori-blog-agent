-- Preserve legacy review attestations as history. New manual clicks record
-- exact-version publication intent; independent safety checks run in code.
ALTER TABLE manual_publication_approval_events
  DROP CONSTRAINT IF EXISTS manual_publication_approval_events_reviewed_exact_content_check,
  DROP CONSTRAINT IF EXISTS manual_publication_approval_ev_assertions_safe_to_publish_check,
  DROP CONSTRAINT IF EXISTS manual_publication_approval_e_rights_privacy_harm_checked_check;

CREATE OR REPLACE FUNCTION require_verified_scheduled_publication_review()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  lane text;
BEGIN
 IF NEW.publishing_record_id IS NOT NULL THEN
   IF NOT EXISTS (
     SELECT 1 FROM publishing_records p JOIN publishing_jobs j ON j.id=p.job_id
     WHERE p.id=NEW.publishing_record_id AND p.blog_id=NEW.blog_id
       AND p.content_version_id=NEW.content_version_id AND p.remote_post_id=NEW.post_id
       AND p.remote_status='LIVE' AND p.remote_verified_at IS NOT NULL
       AND j.publication_lane IN ('scheduled_auto','manual','trends_auto')
   ) THEN
     RAISE EXCEPTION 'post_publication_review_requires_verified_live_record';
   END IF;
   RETURN NEW;
 END IF;

 IF NEW.post_id IS NOT NULL OR NEW.publishing_job_id IS NULL THEN
   RAISE EXCEPTION 'prepublication_review_requires_bound_job';
 END IF;
 SELECT j.publication_lane INTO lane FROM publishing_jobs j
 WHERE j.id=NEW.publishing_job_id AND j.blog_id=NEW.blog_id
   AND j.content_version_id=NEW.content_version_id AND j.simulation_only=false
   AND j.status IN ('queued','running');
 IF lane='scheduled_auto' THEN
   IF NOT EXISTS (
     SELECT 1 FROM publishing_jobs j
     JOIN external_content_import_content_links l ON l.content_version_id=j.content_version_id
     JOIN external_content_imports i ON i.id=l.import_id
     JOIN blogger_blogs b ON b.id=j.blog_id
     JOIN LATERAL (SELECT action,approved_blog_ids FROM scheduled_publication_policy_events
       ORDER BY id DESC LIMIT 1) policy ON policy.action='enabled' AND policy.approved_blog_ids ? b.id::text
     WHERE j.id=NEW.publishing_job_id AND j.publication_lane='scheduled_auto'
       AND j.adapter_type='blogger_live' AND i.id=NEW.import_id
       AND i.generation_method='chatgpt_scheduled_export'
   ) THEN RAISE EXCEPTION 'prepublication_review_requires_active_scheduled_job'; END IF;
 ELSIF lane='trends_auto' THEN
   IF NOT EXISTS (
     SELECT 1 FROM publishing_jobs j
     JOIN external_content_import_content_links l ON l.content_version_id=j.content_version_id
     JOIN external_content_imports i ON i.id=l.import_id
     JOIN codex_authoring_jobs a ON a.import_id=i.id AND a.content_version_id=j.content_version_id
     JOIN trend_generation_requests q ON q.authoring_job_id=a.id
     JOIN LATERAL (SELECT enabled,allowed_geos FROM trends_publication_policy_events
       WHERE blog_id=j.blog_id ORDER BY id DESC LIMIT 1) policy ON policy.enabled
     WHERE j.id=NEW.publishing_job_id AND j.adapter_type='blogger_live'
       AND i.id=NEW.import_id AND i.generation_method='codex_trends_export'
       AND a.job_type='google_trends' AND a.state='imported_review'
       AND q.contract->>'target_blog_id'=j.blog_id::text
       AND q.contract->>'source_country'=ANY(policy.allowed_geos)
   ) THEN RAISE EXCEPTION 'prepublication_review_requires_active_trends_job'; END IF;
 ELSIF lane='manual' THEN
   IF NOT EXISTS (
     SELECT 1 FROM manual_publication_approval_events a
     WHERE a.job_id=NEW.publishing_job_id AND a.blog_id=NEW.blog_id
       AND a.content_version_id=NEW.content_version_id
       AND a.import_id IS NOT DISTINCT FROM NEW.import_id
       AND length(a.title_sha256)=64 AND length(a.body_sha256)=64
       AND length(a.html_sha256)=64
   ) THEN RAISE EXCEPTION 'prepublication_review_requires_manual_user_confirmation'; END IF;
 ELSE
   RAISE EXCEPTION 'prepublication_review_requires_active_publication_job';
 END IF;
 RETURN NEW;
END $$;

INSERT INTO audit_events(event_type,payload) VALUES
  ('schema.manual_publication_intent.migrated',
   '{"version":89,"legacy_review_rows_preserved":true,"new_manual_attestations_default_false":true,"publication_settings_unchanged":true}');
INSERT INTO schema_migrations(version) VALUES (89);
