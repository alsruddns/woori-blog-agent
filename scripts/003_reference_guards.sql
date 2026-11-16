-- Preserve historical identity while allowing non-destructive configuration changes.
CREATE FUNCTION protect_identity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key text;
BEGIN
 FOREACH key IN ARRAY TG_ARGV LOOP
  IF to_jsonb(OLD)->key IS DISTINCT FROM to_jsonb(NEW)->key THEN
   RAISE EXCEPTION 'Historical identity cannot be changed: %',key;
  END IF;
 END LOOP;
 RETURN NEW;
END; $$;
CREATE TRIGGER language_identity BEFORE UPDATE ON languages
 FOR EACH ROW EXECUTE FUNCTION protect_identity('code');
CREATE TRIGGER blog_identity BEFORE UPDATE ON blogger_blogs
 FOR EACH ROW EXECUTE FUNCTION protect_identity('id','language_code','url');
CREATE TRIGGER profile_identity BEFORE UPDATE ON language_profiles
 FOR EACH ROW EXECUTE FUNCTION protect_identity('id','language_code','target_country');
CREATE TRIGGER localization_identity BEFORE UPDATE ON content_localizations
 FOR EACH ROW EXECUTE FUNCTION protect_identity('id','group_id','language_code','target_country');
CREATE TRIGGER policy_identity BEFORE UPDATE ON publishing_policies
 FOR EACH ROW EXECUTE FUNCTION protect_identity('id','language_code','profile_id','blog_id');
CREATE FUNCTION validate_localization_reference() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE language text; country text; expected_language text; expected_country text;
BEGIN
 SELECT l.language_code,l.target_country INTO language,country FROM content_versions v
  JOIN content_localizations l ON l.id=v.localization_id WHERE v.id=NEW.content_version_id;
 IF TG_TABLE_NAME='publishing_jobs' THEN
  SELECT p.language_code,r.target_country INTO expected_language,expected_country
   FROM publishing_policies p JOIN language_profiles r ON r.id=p.profile_id WHERE p.id=NEW.policy_id;
 ELSE
  SELECT p.language_code,p.target_country INTO expected_language,expected_country
   FROM language_profiles p WHERE p.id=NEW.profile_id;
 END IF;
 IF language IS DISTINCT FROM expected_language OR country IS DISTINCT FROM expected_country THEN
  RAISE EXCEPTION 'Localization does not match language/country policy';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER publishing_job_locale BEFORE INSERT OR UPDATE ON publishing_jobs
 FOR EACH ROW EXECUTE FUNCTION validate_localization_reference();
CREATE TRIGGER seo_audit_locale BEFORE INSERT ON seo_audits
 FOR EACH ROW EXECUTE FUNCTION validate_localization_reference();
CREATE TRIGGER publishing_job_identity BEFORE UPDATE ON publishing_jobs
 FOR EACH ROW EXECUTE FUNCTION protect_identity('id','policy_id','blog_id','content_version_id','idempotency_key');
CREATE FUNCTION validate_performance_language() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (SELECT language_code FROM blogger_blogs WHERE id=NEW.blog_id) IS DISTINCT FROM
    (SELECT language_code FROM content_localizations WHERE id=NEW.localization_id) THEN
  RAISE EXCEPTION 'Performance blog/localization language mismatch';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER performance_locale BEFORE INSERT OR UPDATE ON search_performance
 FOR EACH ROW EXECUTE FUNCTION validate_performance_language();
CREATE OR REPLACE FUNCTION audit_configuration() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item jsonb; lang text; blog uuid;
BEGIN
 item := to_jsonb(NEW);
 lang := CASE WHEN TG_TABLE_NAME='languages' THEN item->>'code' ELSE item->>'language_code' END;
 IF item ? 'profile_id' AND lang IS NULL THEN
  SELECT language_code INTO lang FROM language_profiles WHERE id=(item->>'profile_id')::uuid;
 END IF;
 IF TG_TABLE_NAME='blogger_blogs' THEN blog := NEW.id;
 ELSIF TG_TABLE_NAME='publishing_policies' THEN blog := NEW.blog_id; END IF;
 INSERT INTO audit_events(event_type,language_code,blog_id,payload)
 VALUES('config.'||TG_TABLE_NAME||'.'||lower(TG_OP),lang,blog,
  jsonb_build_object('entity_id',COALESCE(item->>'id',item->>'code',item->>'profile_id'),
    'actor',COALESCE(NULLIF(current_setting('woori.actor',true),''),current_user),
    'before_fingerprint',CASE WHEN TG_OP='UPDATE' THEN md5(to_jsonb(OLD)::text) ELSE NULL END,
    'after_fingerprint',md5(item::text)));
 RETURN NEW;
END; $$;
INSERT INTO audit_events(event_type,language_code,payload)
 SELECT 'config.languages.seeded',code,jsonb_build_object('source','migration002') FROM languages;
INSERT INTO audit_events(event_type,payload) VALUES('schema.references.migrated','{"version":3}');
INSERT INTO schema_migrations(version) VALUES(3);
