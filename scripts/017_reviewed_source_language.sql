-- Language attribution belongs to an immutable source review, not a rewrite of source history.
ALTER TABLE source_reviews ADD COLUMN source_language text NOT NULL DEFAULT 'und';
CREATE FUNCTION audit_review_language() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO audit_events(event_type,payload)
 VALUES('research.source_language.reviewed',jsonb_build_object(
   'source_id',NEW.source_id,'source_language',NEW.source_language,
   'approved',NEW.approved,'reviewer',NEW.reviewer,'reason_fingerprint',md5(NEW.reason)));
 RETURN NEW;
END; $$;
CREATE TRIGGER source_language_review_audit AFTER INSERT ON source_reviews
 FOR EACH ROW EXECUTE FUNCTION audit_review_language();
INSERT INTO audit_events(event_type,payload) VALUES('schema.reviewed_source_language.migrated','{"version":17}');
INSERT INTO schema_migrations(version) VALUES(17);
