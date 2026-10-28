CREATE TABLE trend_topic_category_reviews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 topic_id uuid NOT NULL REFERENCES trend_topics(id),
 category_slug text NOT NULL REFERENCES categories(slug),
 decision text NOT NULL CHECK (decision IN ('selected','excluded')),
 reviewer text NOT NULL CHECK (length(trim(reviewer)) BETWEEN 2 AND 120),
 rationale text NOT NULL CHECK (length(trim(rationale)) BETWEEN 10 AND 1000),
 idempotency_key text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER trend_topic_category_review_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON trend_topic_category_reviews FOR EACH STATEMENT EXECUTE FUNCTION deny_trend_research_mutation();
GRANT SELECT,INSERT ON trend_topic_category_reviews TO woori_app;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.trend_topic_categories.migrated',
  '{"version":46,"category_registry":"eight_editorial_categories","automatic_category_inference":false}');
INSERT INTO schema_migrations(version) VALUES(46);
