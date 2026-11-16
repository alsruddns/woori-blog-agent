"""Dry-run by default; explicit immutable manifest and matching SHA required to apply."""
import argparse
import json
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row
from woori.qwen_cleanup import apply, digest, plan

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--manifest',type=Path,required=True)
parser.add_argument('--apply-sha256')
args = parser.parse_args()
with psycopg.connect(str(dotenv_values(root/'.env.migration')['MIGRATION_DATABASE_URL']),row_factory=dict_row) as conn:
    if conn.info.dbname != 'woori_blog_agent':
        raise SystemExit('Wrong operations database')
    if args.apply_sha256:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        if digest(manifest) != args.apply_sha256:
            raise SystemExit('Manifest checksum mismatch')
        print(json.dumps(apply(conn,manifest)))
    else:
        manifest = plan(conn)
        with args.manifest.open('x',encoding='utf-8') as file:
            file.write(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'sha256':digest(manifest),'manuscripts':manifest['manuscripts'],
            'counts':{k:len(v) for k,v in manifest['tables'].items()},'protected_collisions':manifest['protected_collisions']}))
