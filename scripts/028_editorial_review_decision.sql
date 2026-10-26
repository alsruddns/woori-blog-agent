-- Make editorial approval explicit and keep it separate from publication permission.
ALTER TABLE article_human_reviews
 DROP CONSTRAINT article_human_reviews_disposition_check;
ALTER TABLE article_human_reviews
 ADD CONSTRAINT article_human_reviews_disposition_check
 CHECK(disposition IN ('reviewed','approved','revision_requested','rejected')),
 ADD CONSTRAINT article_human_reviews_approval_checks
 CHECK(disposition <> 'approved' OR (
   factual_accuracy='verified'
   AND translation_naturalness='acceptable'
   AND reader_value='useful'
 ));
INSERT INTO audit_events(event_type,payload)
 VALUES('schema.editorial_review_decision.migrated',
   '{"version":28,"editorial_approval_separate_from_publication":true,"publish_ready_changes":false}');
INSERT INTO schema_migrations(version) VALUES(28);
