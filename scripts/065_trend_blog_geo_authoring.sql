-- Explicit Trends authoring geography mapping, separate from any publication policy.
CREATE TABLE trend_blog_geo_authoring (
 blog_id uuid NOT NULL REFERENCES blogger_blogs(id),
 geo text NOT NULL CHECK(geo IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH')),
 enabled boolean NOT NULL DEFAULT false,
 processing_order integer NOT NULL CHECK(processing_order BETWEEN 1 AND 11),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(blog_id,geo)
);
CREATE UNIQUE INDEX trend_blog_geo_authoring_enabled_geo
 ON trend_blog_geo_authoring(geo) WHERE enabled;
CREATE UNIQUE INDEX trend_blog_geo_authoring_blog_order
 ON trend_blog_geo_authoring(blog_id,processing_order) WHERE enabled;

-- Seed only already registered exact locale/country pairs. Cross-country
-- mappings require an explicit operator action in the Trends dashboard.
INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order)
SELECT b.id,lp.target_country,true,1
FROM blogger_blogs b
JOIN publishing_policies p ON p.blog_id=b.id
JOIN language_profiles lp ON lp.id=p.profile_id AND lp.language_code=b.language_code
WHERE b.active AND b.blog_id IS NOT NULL
  AND lp.target_country IN ('KR','US','JP','TW','HK','SG','GB','CA','AU','IN','PH')
GROUP BY b.id,lp.target_country
HAVING count(DISTINCT lp.target_country)=1;
GRANT SELECT,INSERT,UPDATE ON trend_blog_geo_authoring TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES('schema.trend_blog_geo_authoring.migrated',
 '{"version":65,"exact_region_defaults_only":true,"cross_region_requires_operator":true,"publication_authority":false}');
INSERT INTO schema_migrations(version) VALUES(65);
