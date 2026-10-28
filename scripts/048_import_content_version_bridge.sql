-- Link immutable external import versions into the existing manuscript index.
CREATE TABLE external_content_import_groups (
 event_group_id text PRIMARY KEY,
 content_group_id uuid NOT NULL UNIQUE REFERENCES content_groups(id),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE external_content_import_content_links (
 import_id uuid NOT NULL,
 import_version_id uuid NOT NULL,
 content_version_id uuid NOT NULL UNIQUE REFERENCES content_versions(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(import_id,import_version_id),
 FOREIGN KEY(import_id,import_version_id)
   REFERENCES external_content_import_versions(import_id,id)
);
CREATE TRIGGER external_import_groups_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_import_groups FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
CREATE TRIGGER external_import_content_links_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON external_content_import_content_links FOR EACH STATEMENT EXECUTE FUNCTION deny_mutation();
GRANT SELECT,INSERT ON external_content_import_groups,external_content_import_content_links TO woori_app;
DO $$
DECLARE item record; parent_version uuid; v_group_id uuid; v_localization_id uuid;
        v_next_version integer; content_version_id uuid; v_target_country text;
BEGIN
 FOR item IN
  SELECT i.id AS import_id,i.external_content_id,i.event_group_id,i.parent_content_id,
         i.relation,i.language_code,i.target_audiences,i.title AS imported_title,i.body_markdown AS imported_body,
         i.received_at,v.id AS import_version_id,v.version_number,v.parent_version_id AS import_parent_version_id,
         v.title,v.body_markdown
  FROM external_content_imports i
  JOIN external_content_import_versions v ON v.import_id=i.id
  ORDER BY i.received_at,i.id,v.version_number
 LOOP
  SELECT content_group_id INTO v_group_id FROM external_content_import_groups
   WHERE event_group_id=item.event_group_id;
  IF v_group_id IS NULL THEN
   INSERT INTO content_groups DEFAULT VALUES RETURNING id INTO v_group_id;
   INSERT INTO external_content_import_groups(event_group_id,content_group_id)
    VALUES(item.event_group_id,v_group_id);
  END IF;
  SELECT COALESCE((SELECT NULLIF(a.value->>'target_region','')
    FROM jsonb_array_elements(item.target_audiences) a
    WHERE a.value->>'language_code'=item.language_code LIMIT 1),'') INTO v_target_country;
  INSERT INTO content_localizations(group_id,language_code,target_country)
   VALUES(v_group_id,item.language_code,v_target_country)
   ON CONFLICT(group_id,language_code,target_country) DO NOTHING;
  SELECT l.id INTO v_localization_id FROM content_localizations l
   WHERE l.group_id=v_group_id AND l.language_code=item.language_code AND l.target_country=v_target_country;
  parent_version := NULL;
  IF item.import_parent_version_id IS NOT NULL THEN
   SELECT l.content_version_id INTO parent_version FROM external_content_import_content_links l
    WHERE l.import_id=item.import_id AND l.import_version_id=item.import_parent_version_id;
  ELSIF item.parent_content_id IS NOT NULL THEN
   SELECT l.content_version_id INTO parent_version
   FROM external_content_imports p
   JOIN external_content_import_content_links l ON l.import_id=p.id
   JOIN external_content_import_versions pv ON pv.import_id=l.import_id AND pv.id=l.import_version_id
   WHERE p.external_content_id=item.parent_content_id AND p.event_group_id=item.event_group_id
   ORDER BY pv.version_number DESC LIMIT 1;
  END IF;
  SELECT COALESCE(MAX(v.version),0)+1 INTO v_next_version FROM content_versions v
   WHERE v.localization_id=v_localization_id;
  INSERT INTO content_versions(group_id,language,localization_id,version,title,body,source_version_id)
   VALUES(v_group_id,item.language_code,v_localization_id,v_next_version,item.title,item.body_markdown,parent_version)
   RETURNING id INTO content_version_id;
  INSERT INTO external_content_import_content_links(import_id,import_version_id,content_version_id)
   VALUES(item.import_id,item.import_version_id,content_version_id);
 END LOOP;
END $$;
INSERT INTO audit_events(event_type,payload) VALUES
 ('schema.import_content_version_bridge.migrated',
  '{"version":48,"source_imports_preserved":true,"publish_ready":false,"blogger_calls":0}');
INSERT INTO schema_migrations(version) VALUES(48);
