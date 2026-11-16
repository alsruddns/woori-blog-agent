-- Restore missing defaults for the original English, Korean, and Japanese
-- country profiles. Preserve any operator-authored nonblank policy text.
WITH updated AS (
  UPDATE language_profiles
  SET search_intent=COALESCE(NULLIF(btrim(search_intent),''),
        'Country-specific, source-led news and analysis for local readers.'),
      generation_policy=COALESCE(NULLIF(btrim(generation_policy),''),
        'Use reviewed source evidence and the existing scheduled-export workflow; no local generation adapter is enabled.'),
      localization_policy=COALESCE(NULLIF(btrim(localization_policy),''),
        'Write in the registered BCP 47 language for the target country; do not disguise foreign news as local.'),
      seo_policy=COALESCE(NULLIF(btrim(seo_policy),''),
        'Apply language-specific title, summary, search intent, and verified labels; do not claim unverified SEO checks.')
  WHERE (language_code,target_country) IN (('en','US'),('ko','KR'),('ja','JP'))
    AND (btrim(search_intent)='' OR btrim(generation_policy)='' OR
         btrim(localization_policy)='' OR btrim(seo_policy)='')
  RETURNING id,language_code,target_country
)
INSERT INTO audit_events(event_type,payload)
SELECT 'language.country_policy_defaults.restored',
       jsonb_build_object('profile_id',id,'language',language_code,'country',target_country,
         'defaults_only_for_empty_fields',true,'generation_and_publication_approval_granted',false)
FROM updated;

WITH activated AS (
  UPDATE publishing_policies p SET active=true
  FROM blogger_blogs b,language_profiles lp
  WHERE p.blog_id=b.id AND p.profile_id=lp.id
    AND lp.language_code=b.language_code
    AND (lp.language_code,lp.target_country) IN (('en','US'),('ko','KR'),('ja','JP'))
    AND b.active AND NOT p.active
  RETURNING p.id,p.blog_id,b.language_code,lp.target_country
)
INSERT INTO audit_events(event_type,blog_id,payload)
SELECT 'blogger.country_publication_policy.activated',blog_id,
       jsonb_build_object('policy_id',id,'language',language_code,'country',target_country,
         'reason','Restore requested country profile policy; independent content and external-write gates remain required',
         'automatic_publication_authorized',false)
FROM activated;

INSERT INTO schema_migrations(version) VALUES(87);
