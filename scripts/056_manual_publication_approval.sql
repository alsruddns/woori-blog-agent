-- Bind each manual public-publish request to the exact immutable payload and
-- explicit Dashboard confirmation. These records are append-only.
CREATE TABLE manual_publication_approval_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 job_id uuid NOT NULL UNIQUE REFERENCES publishing_jobs(id),
 blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 content_version_id uuid NOT NULL REFERENCES content_versions(id),
 import_id uuid REFERENCES external_content_imports(id),
 title_sha256 char(64) NOT NULL CHECK(title_sha256 ~ '^[0-9a-f]{64}$'),
 body_sha256 char(64) NOT NULL CHECK(body_sha256 ~ '^[0-9a-f]{64}$'),
 html_sha256 char(64) NOT NULL CHECK(html_sha256 ~ '^[0-9a-f]{64}$'),
 actor_label text NOT NULL CHECK(length(trim(actor_label)) BETWEEN 2 AND 120),
 reason text NOT NULL CHECK(length(trim(reason)) BETWEEN 10 AND 2000),
 reviewed_exact_content boolean NOT NULL CHECK(reviewed_exact_content),
 assertions_safe_to_publish boolean NOT NULL CHECK(assertions_safe_to_publish),
 rights_privacy_harm_checked boolean NOT NULL CHECK(rights_privacy_harm_checked),
 idempotency_key text NOT NULL UNIQUE CHECK(length(idempotency_key) BETWEEN 16 AND 128),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER manual_publication_approval_events_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON manual_publication_approval_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();

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
       AND j.publication_lane IN ('scheduled_auto','manual')
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
 ELSIF lane='manual' THEN
   IF NOT EXISTS (
     SELECT 1 FROM manual_publication_approval_events a
     WHERE a.job_id=NEW.publishing_job_id AND a.blog_id=NEW.blog_id
       AND a.content_version_id=NEW.content_version_id
       AND a.import_id IS NOT DISTINCT FROM NEW.import_id
       AND a.reviewed_exact_content AND a.assertions_safe_to_publish
       AND a.rights_privacy_harm_checked
   ) THEN RAISE EXCEPTION 'prepublication_review_requires_manual_user_confirmation'; END IF;
 ELSE
   RAISE EXCEPTION 'prepublication_review_requires_active_publication_job';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER verified_scheduled_review_only ON post_publication_reviews;
CREATE TRIGGER verified_scheduled_review_only BEFORE INSERT OR UPDATE ON post_publication_reviews
 FOR EACH ROW EXECUTE FUNCTION require_verified_scheduled_publication_review();

GRANT SELECT,INSERT ON manual_publication_approval_events TO woori_app;
GRANT USAGE,SELECT ON SEQUENCE manual_publication_approval_events_id_seq TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.manual_publication_approval.migrated',
  '{"version":56,"exact_payload_confirmation":true,"append_only_approval":true,"live_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(56);
