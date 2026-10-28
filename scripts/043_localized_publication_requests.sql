-- Persist explicit language-extension requests without invoking a generator or Blogger.
CREATE TABLE localized_publication_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 source_evaluation_id uuid NOT NULL,
 source_content_version_id uuid NOT NULL REFERENCES content_versions(id),
 source_localization_id uuid NOT NULL REFERENCES content_localizations(id),
 source_group_id uuid NOT NULL,
 source_language_code text NOT NULL REFERENCES languages(code),
 source_body_sha256 char(64) NOT NULL CHECK(source_body_sha256 ~ '^[0-9a-f]{64}$'),
 target_language_code text NOT NULL REFERENCES languages(code),
 target_blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 requested_by text NOT NULL CHECK(length(requested_by) BETWEEN 2 AND 80),
 idempotency_key text NOT NULL UNIQUE CHECK(idempotency_key ~ '^[A-Za-z0-9_-]{12,160}$'),
 publication_mode_at_request text NOT NULL CHECK(publication_mode_at_request IN ('manual','auto')),
 one_time_auto_publish_requested boolean NOT NULL DEFAULT false,
 initial_state text NOT NULL CHECK(initial_state IN (
   'blocked_evaluation_only','blocked_source_provenance_unverified',
   'blocked_source_quality','existing_localization_requires_review','awaiting_provider'
 )),
 existing_target_content_version_id uuid REFERENCES content_versions(id),
 blockers jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(blockers)='array'),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(source_group_id,target_language_code,target_blog_id),
 CHECK(source_language_code <> target_language_code)
);

CREATE TABLE localized_publication_request_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 request_id uuid NOT NULL REFERENCES localized_publication_requests(id),
 event_key text NOT NULL UNIQUE CHECK(event_key ~ '^[A-Za-z0-9_-]{12,160}$'),
 event_type text NOT NULL CHECK(event_type IN ('requested','state_changed','cancelled')),
 state text NOT NULL CHECK(state IN (
   'blocked_evaluation_only','blocked_source_provenance_unverified',
   'blocked_source_quality','existing_localization_requires_review','awaiting_provider',
   'awaiting_manual_review','ready_for_publication','blocked_publication','cancelled','published'
 )),
 actor text NOT NULL CHECK(length(actor) BETWEEN 2 AND 80),
 reason text NOT NULL CHECK(length(reason) BETWEEN 2 AND 1000),
 details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(details)='object'),
 created_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION validate_localized_publication_request() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_language text; source_group uuid; mapped_language text;
BEGIN
 SELECT language_code,group_id INTO source_language,source_group
   FROM content_localizations WHERE id=NEW.source_localization_id;
 SELECT language_code INTO mapped_language FROM blogger_blogs
   WHERE id=NEW.target_blog_id AND active;
 IF source_language IS NULL OR source_language<>NEW.source_language_code
   OR source_group IS NULL OR source_group<>NEW.source_group_id THEN
   RAISE EXCEPTION 'localized request source identity mismatch';
 END IF;
 IF mapped_language IS NULL OR mapped_language<>NEW.target_language_code THEN
   RAISE EXCEPTION 'localized request target blog language mismatch';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER localized_publication_request_target
 BEFORE INSERT ON localized_publication_requests
 FOR EACH ROW EXECUTE FUNCTION validate_localized_publication_request();
CREATE TRIGGER localized_publication_request_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON localized_publication_requests
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER localized_publication_event_immutable
 BEFORE UPDATE OR DELETE OR TRUNCATE ON localized_publication_request_events
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();

GRANT SELECT,INSERT ON localized_publication_requests,localized_publication_request_events TO woori_app;
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.localized_publication_requests.migrated',
   '{"version":43,"generation_provider_attached":false,"live_blogger_writes_enabled":false}');
INSERT INTO schema_migrations(version) VALUES(43);
