-- Additive migration: preserve original version UUIDs, bodies and audit history.
CREATE TABLE languages (
 code text PRIMARY KEY CHECK(code ~ '^[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*$'),
 display_name text NOT NULL CHECK(length(display_name) BETWEEN 1 AND 100),
 active boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX language_code_case ON languages(lower(code));
CREATE TABLE language_profiles (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), language_code text NOT NULL REFERENCES languages(code),
 target_country text NOT NULL DEFAULT '' CHECK(target_country='' OR target_country ~ '^([A-Z]{2}|[0-9]{3})$'),
 search_intent text NOT NULL DEFAULT '', generation_policy text NOT NULL DEFAULT '',
 localization_policy text NOT NULL DEFAULT '', seo_policy text NOT NULL DEFAULT '',
 UNIQUE(language_code,target_country), UNIQUE(id,language_code));
CREATE TABLE language_capabilities (
 profile_id uuid PRIMARY KEY REFERENCES language_profiles(id),
 generation_supported boolean NOT NULL DEFAULT false,
 translation_supported boolean NOT NULL DEFAULT false,
 quality_supported boolean NOT NULL DEFAULT false,
 model_adapter text, validator_adapter text, verified_at timestamptz,
 CHECK(NOT (generation_supported OR translation_supported OR quality_supported)
       OR (verified_at IS NOT NULL AND model_adapter IS NOT NULL AND validator_adapter IS NOT NULL)));
CREATE TABLE blogger_blogs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), language_code text NOT NULL REFERENCES languages(code),
 url text UNIQUE NOT NULL CHECK(url ~ '^https://[a-z0-9][a-z0-9-]*\.blogspot\.com$'),
 display_name text NOT NULL CHECK(length(display_name) BETWEEN 1 AND 100),
 active boolean NOT NULL DEFAULT true,
 blog_id text UNIQUE CHECK(blog_id ~ '^[0-9]+$'),
 connection_verified_at timestamptz, test_publish_verified_at timestamptz,
 UNIQUE(id,language_code),
 CHECK(connection_verified_at IS NULL OR blog_id IS NOT NULL),
 CHECK(test_publish_verified_at IS NULL OR connection_verified_at IS NOT NULL));
CREATE TABLE content_localizations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), group_id uuid NOT NULL REFERENCES content_groups(id),
 language_code text NOT NULL REFERENCES languages(code),
 target_country text NOT NULL DEFAULT '' CHECK(target_country='' OR target_country ~ '^([A-Z]{2}|[0-9]{3})$'),
 UNIQUE(group_id,language_code,target_country), UNIQUE(id,group_id,language_code));
INSERT INTO languages(code,display_name) VALUES ('ko','한국어'),('en','English'),('zh-CN','简体中文'),('ja','日本語');
INSERT INTO language_profiles(language_code) SELECT code FROM languages;
INSERT INTO language_capabilities(profile_id) SELECT id FROM language_profiles;
INSERT INTO content_localizations(group_id,language_code) SELECT DISTINCT group_id,language FROM content_versions;
ALTER TABLE content_versions ADD COLUMN localization_id uuid;
-- An exclusive transactional metadata backfill; original content fields never change.
ALTER TABLE content_versions DISABLE TRIGGER content_immutable;
UPDATE content_versions v SET localization_id=l.id FROM content_localizations l
 WHERE l.group_id=v.group_id AND l.language_code=v.language AND l.target_country='';
ALTER TABLE content_versions ENABLE TRIGGER content_immutable;
ALTER TABLE content_versions ALTER COLUMN localization_id SET NOT NULL;
ALTER TABLE content_versions DROP CONSTRAINT content_versions_language_check;
ALTER TABLE content_versions DROP CONSTRAINT content_versions_group_id_language_version_key;
ALTER TABLE content_versions ADD CONSTRAINT version_localization_fk
 FOREIGN KEY(localization_id,group_id,language) REFERENCES content_localizations(id,group_id,language_code);
ALTER TABLE content_versions ADD UNIQUE(localization_id,version);
ALTER TABLE content_versions ADD UNIQUE(group_id,id);
ALTER TABLE content_versions ADD CONSTRAINT source_same_group FOREIGN KEY(group_id,source_version_id)
 REFERENCES content_versions(group_id,id);
CREATE FUNCTION resolve_localization() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.localization_id IS NULL THEN
  INSERT INTO content_localizations(group_id,language_code) VALUES(NEW.group_id,NEW.language)
   ON CONFLICT(group_id,language_code,target_country) DO NOTHING;
  SELECT id INTO NEW.localization_id FROM content_localizations
   WHERE group_id=NEW.group_id AND language_code=NEW.language AND target_country='';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER version_localization BEFORE INSERT ON content_versions
 FOR EACH ROW EXECUTE FUNCTION resolve_localization();
CREATE TABLE categories(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), slug text UNIQUE NOT NULL);
CREATE TABLE category_localizations (
 category_id uuid NOT NULL REFERENCES categories(id), profile_id uuid NOT NULL REFERENCES language_profiles(id),
 display_name text NOT NULL, PRIMARY KEY(category_id,profile_id));
CREATE TABLE localization_categories (
 localization_id uuid NOT NULL REFERENCES content_localizations(id), category_id uuid NOT NULL REFERENCES categories(id),
 PRIMARY KEY(localization_id,category_id));
CREATE TABLE glossary_entries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), profile_id uuid NOT NULL REFERENCES language_profiles(id),
 source_term text NOT NULL, localized_term text NOT NULL, notes text NOT NULL DEFAULT '',
 UNIQUE(profile_id,source_term));
CREATE TABLE publishing_policies (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), language_code text NOT NULL REFERENCES languages(code),
 blog_id uuid NOT NULL, profile_id uuid NOT NULL, active boolean NOT NULL DEFAULT false,
 timezone text NOT NULL DEFAULT 'UTC', schedule_cron text NOT NULL DEFAULT '0 9 * * *',
 auto_publish_allowed boolean NOT NULL DEFAULT false CHECK(NOT auto_publish_allowed),
 FOREIGN KEY(blog_id,language_code) REFERENCES blogger_blogs(id,language_code),
 FOREIGN KEY(profile_id,language_code) REFERENCES language_profiles(id,language_code),
 UNIQUE(blog_id,profile_id), UNIQUE(id,blog_id));
CREATE TABLE publishing_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), policy_id uuid NOT NULL, blog_id uuid NOT NULL,
 content_version_id uuid NOT NULL REFERENCES content_versions(id),
 idempotency_key text UNIQUE NOT NULL, scheduled_at timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'blocked' CHECK(status IN ('blocked','queued','running','succeeded','failed')),
 run_id uuid REFERENCES job_runs(id),
 FOREIGN KEY(policy_id,blog_id) REFERENCES publishing_policies(id,blog_id), UNIQUE(id,blog_id,content_version_id));
CREATE TABLE publishing_records (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid NOT NULL,
 blog_id uuid NOT NULL, content_version_id uuid NOT NULL, remote_post_id text NOT NULL,
 published_at timestamptz NOT NULL, UNIQUE(blog_id,remote_post_id), UNIQUE(blog_id,content_version_id),
 FOREIGN KEY(job_id,blog_id,content_version_id) REFERENCES publishing_jobs(id,blog_id,content_version_id));
CREATE TRIGGER publishing_record_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON publishing_records
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TABLE seo_audits (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), content_version_id uuid NOT NULL REFERENCES content_versions(id),
 profile_id uuid NOT NULL REFERENCES language_profiles(id), passed boolean NOT NULL DEFAULT false,
 validator_adapter text NOT NULL, checks jsonb NOT NULL CHECK(jsonb_typeof(checks)='object'),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TRIGGER seo_audit_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON seo_audits
 FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TABLE search_performance (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 localization_id uuid NOT NULL REFERENCES content_localizations(id), country text NOT NULL,
 period_start date NOT NULL, period_end date NOT NULL CHECK(period_end>=period_start),
 clicks bigint NOT NULL CHECK(clicks>=0), impressions bigint NOT NULL CHECK(impressions>=0),
 created_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE audit_events ADD COLUMN language_code text REFERENCES languages(code);
ALTER TABLE audit_events ADD COLUMN blog_id uuid REFERENCES blogger_blogs(id);
CREATE FUNCTION audit_configuration() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item jsonb; lang text; blog uuid;
BEGIN
 item := to_jsonb(NEW);
 lang := CASE WHEN TG_TABLE_NAME='languages' THEN item->>'code' ELSE item->>'language_code' END;
 IF TG_TABLE_NAME='blogger_blogs' THEN blog := NEW.id; END IF;
 INSERT INTO audit_events(event_type,language_code,blog_id,payload)
 VALUES('config.'||TG_TABLE_NAME||'.'||lower(TG_OP),lang,blog,
  jsonb_build_object('entity_id',COALESCE(item->>'id',item->>'code',item->>'profile_id'),
    'actor',COALESCE(NULLIF(current_setting('woori.actor',true),''),current_user),
    'before_fingerprint',CASE WHEN TG_OP='UPDATE' THEN md5(to_jsonb(OLD)::text) ELSE NULL END,
    'after_fingerprint',md5(item::text)));
 RETURN NEW;
END; $$;
-- Trigger executes as invoker; runtime must be able to append audits. Failure rolls back settings.
CREATE TRIGGER language_audit AFTER INSERT OR UPDATE ON languages FOR EACH ROW EXECUTE FUNCTION audit_configuration();
CREATE TRIGGER profile_audit AFTER INSERT OR UPDATE ON language_profiles FOR EACH ROW EXECUTE FUNCTION audit_configuration();
CREATE TRIGGER capability_audit AFTER INSERT OR UPDATE ON language_capabilities FOR EACH ROW EXECUTE FUNCTION audit_configuration();
CREATE TRIGGER blog_audit AFTER INSERT OR UPDATE ON blogger_blogs FOR EACH ROW EXECUTE FUNCTION audit_configuration();
CREATE TRIGGER policy_audit AFTER INSERT OR UPDATE ON publishing_policies FOR EACH ROW EXECUTE FUNCTION audit_configuration();
CREATE TRIGGER glossary_audit AFTER INSERT OR UPDATE ON glossary_entries FOR EACH ROW EXECUTE FUNCTION audit_configuration();
CREATE TRIGGER category_name_audit AFTER INSERT OR UPDATE ON category_localizations FOR EACH ROW EXECUTE FUNCTION audit_configuration();
INSERT INTO blogger_blogs(language_code,url,display_name) VALUES
 ('ko','https://trend-ko.blogspot.com','Trend KO'),
 ('en','https://trend-journal-en.blogspot.com','Trend Journal EN'),
 ('zh-CN','https://trend-zh.blogspot.com','Trend ZH'),
 ('ja','https://trend-ja.blogspot.com','Trend JA');
INSERT INTO publishing_policies(language_code,blog_id,profile_id)
 SELECT b.language_code,b.id,p.id FROM blogger_blogs b JOIN language_profiles p USING(language_code);
INSERT INTO audit_events(event_type,payload) VALUES('schema.multilingual.migrated','{"version":2,"seed_languages":4}');
GRANT SELECT ON languages,language_profiles,language_capabilities,blogger_blogs,content_localizations,
 categories,category_localizations,localization_categories,glossary_entries,publishing_policies,
 publishing_jobs,publishing_records,seo_audits,search_performance TO woori_app;
GRANT INSERT,UPDATE ON languages,language_profiles,blogger_blogs,category_localizations,glossary_entries,publishing_policies TO woori_app;
GRANT INSERT ON language_capabilities,content_localizations TO woori_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO woori_app;
INSERT INTO schema_migrations(version) VALUES(2);
