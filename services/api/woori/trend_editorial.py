"""Audited Trends triage and durable authoring handoff, separate from publication approval."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import topics, trends
from .db import connection
from .editorial_taxonomy import EDITORIAL_CATEGORIES

router = APIRouter(prefix='/admin/research/trend-editorial')
STATES = {'collected','pending_classification','selected','review_candidate','discarded',
          'generation_queued','generating','imported','published','failed'}


def latest(conn: Any, topic_id: UUID) -> dict[str, Any] | None:
    row=conn.execute('SELECT * FROM trend_editorial_events WHERE topic_id=%s ORDER BY id DESC LIMIT 1', (topic_id,)).fetchone()
    return dict(row) if row else None


def transition(conn: Any, topic_id: UUID, state: str, code: str, reason: str,
               actor: str, *, category: str | None = None, evidence: Any = None,
               key: UUID | None = None) -> dict[str, Any]:
    assert state in STATES
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('trend-editorial:'+str(topic_id),))
    prior = latest(conn, topic_id)
    request_key = key or uuid4()
    existing = conn.execute('SELECT * FROM trend_editorial_events WHERE request_key=%s',(request_key,)).fetchone()
    if existing:
        if existing['topic_id'] != topic_id or existing['state'] != state or existing['reason'] != reason:
            raise HTTPException(409,'trend_transition_key_conflict')
        return dict(existing)
    row = conn.execute('''INSERT INTO trend_editorial_events(topic_id,previous_state,state,reason_code,reason,actor,category,evidence,request_key)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
        (topic_id, prior['state'] if prior else None,state,code,reason,actor,category,Jsonb(evidence or {}),request_key)).fetchone()
    conn.execute("INSERT INTO audit_events(event_type,payload) VALUES('trend.editorial.transition',%s)",
        (Jsonb({'topic_id':str(topic_id),'previous_state':prior['state'] if prior else None,
                'state':state,'reason_code':code,'actor':actor,'request_key':str(request_key)}),))
    return dict(row)


def classify(query: str, payload: dict[str, Any] | None) -> tuple[str,str,str | None]:
    key=topics.normalize_query(query)
    domains=topics.research_domains(query)
    if not key or key in topics.BROAD_QUERIES:
        return 'discarded','unclear_search_intent',None
    if any(term in key for term in ('rumor','leaked private','사생활','루머','불륜','열애설')):
        return 'discarded','unverifiable_rumor',None
    category=domains[0] if domains else None
    # Feed headlines provide research context, never factual verification.
    if domains and payload and payload.get('news_items'):
        return 'selected','specific_topic_with_news_context',category
    return 'review_candidate','insufficient_context',category


def reconcile(limit: int = 200) -> dict[str,int]:
    """Bounded backlog, existing exact-query groups; no lexical cross-language auto merges."""
    with connection() as conn:
        rows=conn.execute('''SELECT o.* FROM trend_observations o
            WHERE NOT EXISTS(SELECT 1 FROM trend_topic_memberships m WHERE m.observation_id=o.id)
            ORDER BY collected_at DESC,id LIMIT %s''',(limit,)).fetchall()
        for row in rows:
            key=topics.normalize_query(row['query'])
            if not key:continue
            topic_id=uuid5(NAMESPACE_URL,f"woori-blog-trend-topic:{row['geo']}:{key}")
            conn.execute('''INSERT INTO trend_topics(id,normalized_key,representative_geo,representative_query,
                source_language,grouping_method,grouping_confidence,grouping_status)
                VALUES(%s,%s,%s,%s,%s,'same_query_same_geo',0.9,'exact_query_cluster_not_event_confirmed')
                ON CONFLICT DO NOTHING''',(topic_id,key,row['geo'],row['query'],row['source_language'] or 'und'))
            conn.execute('''INSERT INTO trend_topic_memberships(topic_id,observation_id,grouping_rationale)
                VALUES(%s,%s,'Exact normalized same-region query; event identity requires research.') ON CONFLICT DO NOTHING''',
                (topic_id,row['id']))
        unclassified=conn.execute('''SELECT t.*,o.raw_payload FROM trend_topics t
            JOIN LATERAL(SELECT o.raw_payload FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id
              WHERE m.topic_id=t.id ORDER BY o.collected_at DESC LIMIT 1)o ON true
            WHERE NOT EXISTS(SELECT 1 FROM trend_editorial_events e WHERE e.topic_id=t.id)
            ORDER BY t.created_at DESC LIMIT %s''',(limit,)).fetchall()
        counts:dict[str,int]={}
        for topic in unclassified:
            state,code,category=classify(topic['representative_query'],topic['raw_payload'])
            transition(conn,topic['id'],state,code,
                '규칙 기반 조사 후보 선정입니다. 뉴스 사실·권리 검증이나 공개 게시 승인이 아닙니다.' if state=='selected'
                else '검색 의도가 불명확하거나 안전한 기사 작성을 위한 맥락이 부족합니다.',
                'system:trend-editorial-v1',category=category,evidence={'rule_version':1,'score':None,
                'cross_language_event_identity':'unconfirmed','remote_duplicate_status':'not_checked'})
            counts[state]=counts.get(state,0)+1
        return counts


BASE='''FROM trend_observations o
 LEFT JOIN LATERAL(SELECT t.* FROM trend_topic_memberships m JOIN trend_topics t ON t.id=m.topic_id
   WHERE m.observation_id=o.id ORDER BY m.created_at DESC LIMIT 1)t ON true
 LEFT JOIN LATERAL(SELECT * FROM trend_editorial_events e WHERE e.topic_id=t.id ORDER BY id DESC LIMIT 1)e ON true
 LEFT JOIN LATERAL(SELECT * FROM trend_generation_requests q WHERE q.topic_id=t.id ORDER BY created_at DESC LIMIT 1)g ON true
 LEFT JOIN codex_authoring_jobs j ON j.id=g.authoring_job_id'''


@router.get('')
def listing(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),
            q:str=Query('',max_length=200),geo:str=Query('',max_length=2),
            status:str=Query('',max_length=40),category:str=Query('',max_length=100),
            since:datetime|None=None,until:datetime|None=None) -> dict[str,Any]:
    filters=[];params:list[Any]=[]
    for condition,value in (("o.query ILIKE %s",'%'+q.strip()+'%' if q.strip() else None),
        ('o.geo=%s',geo.upper() or None),("COALESCE(e.state,'pending_classification')=%s",status or None),
        ('e.category=%s',category or None),('o.collected_at>=%s',since),('o.collected_at<=%s',until)):
        if value is not None:filters.append(condition);params.append(value)
    if status and status not in STATES:raise HTTPException(422,'unknown_trend_state')
    if any(v and (v.tzinfo is None or v.utcoffset() is None) for v in (since,until)):
        raise HTTPException(422,'timezone_required')
    where=' WHERE '+' AND '.join(filters) if filters else ''
    with connection() as conn:
        total_row=conn.execute('SELECT count(*) n '+BASE+where,params).fetchone()
        total=total_row['n'] if total_row else 0
        items=conn.execute('''SELECT o.*,t.id topic_id,t.representative_query,t.grouping_status,
          COALESCE(e.state,'pending_classification') editorial_state,e.category internal_category,e.reason_code,e.reason,
          g.id generation_request_id,g.state generation_state,j.id authoring_job_id,j.state authoring_state,j.import_id,j.content_version_id
          '''+BASE+where+' ORDER BY o.collected_at DESC,o.id LIMIT %s OFFSET %s',
          [*params,page_size,(page-1)*page_size]).fetchall()
        summary=conn.execute('''SELECT count(*) total,count(*) FILTER(WHERE o.collected_at>=now()-interval '24 hours') last24,
          count(*) FILTER(WHERE e.state='selected') selected,count(*) FILTER(WHERE e.state='discarded') discarded,
          count(*) FILTER(WHERE e.state IS NULL OR e.state IN ('pending_classification','review_candidate')) pending,
          count(*) FILTER(WHERE e.state='generation_queued') generation_queued '''+BASE).fetchone()
        from .keyword_jobs import targets
        blogs=targets(conn)
    return {'items':items,'total':total,'page':page,'page_size':page_size,'summary':summary,'blogs':blogs,
            'geos':sorted(trends.ALLOWED_GEOS),'categories':list(EDITORIAL_CATEGORIES),
            'summary_unit':'observations; one topic may have many observations',
            'schedule':'KST hourly sweep begins at :00; 5-minute global request spacing; 12/hour hard cap'}


@router.get('/{observation_id}')
def detail(observation_id:UUID) -> dict[str,Any]:
    with connection() as conn:
        observation=conn.execute('SELECT * FROM trend_observations WHERE id=%s',(observation_id,)).fetchone()
        if not observation:raise HTTPException(404,'observation_not_found')
        membership=conn.execute('SELECT topic_id FROM trend_topic_memberships WHERE observation_id=%s ORDER BY created_at DESC LIMIT 1',(observation_id,)).fetchone()
        topic_id=membership['topic_id'] if membership else None
        related=conn.execute('''SELECT o.* FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id
            WHERE m.topic_id=%s ORDER BY o.collected_at DESC LIMIT 100''',(topic_id,)).fetchall() if topic_id else []
        history=conn.execute('SELECT * FROM trend_editorial_events WHERE topic_id=%s ORDER BY id DESC',(topic_id,)).fetchall() if topic_id else []
        queue=conn.execute('SELECT * FROM trend_generation_requests WHERE topic_id=%s ORDER BY created_at DESC',(topic_id,)).fetchall() if topic_id else []
        return {'observation':observation,'topic_id':topic_id,'related':related,'history':history,'generation_requests':queue,
                'grouping_warning':'같은 지역·정규화 검색어 그룹이며 동일 사건 확정이 아닙니다. 다른 언어·사건을 자동 병합하지 않습니다.'}


class Decision(BaseModel):
    request_key:UUID
    action:Literal['select','discard','reevaluate','queue']
    reason:str=Field(min_length=3,max_length=2000)
    category:str|None=None
    blog_id:UUID|None=None


def queue_topic(conn:Any,topic_id:UUID,blog_id:UUID) -> dict[str,Any]:
    from .keyword_jobs import targets
    current=latest(conn,topic_id)
    if not current or current['state'] not in {'selected','generation_queued'}:raise HTTPException(409,'topic_not_selected')
    topic=conn.execute('SELECT * FROM trend_topics WHERE id=%s',(topic_id,)).fetchone()
    blog=next((b for b in targets(conn) if b['id']==blog_id),None)
    if not blog or blog['target_country']!=topic['representative_geo']:
        raise HTTPException(409,'exact_region_blog_policy_required')
    category=current['category']
    if category not in {c['slug'] for c in EDITORIAL_CATEGORIES}:raise HTTPException(409,'editorial_category_required')
    observations=conn.execute('''SELECT o.* FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id
        WHERE m.topic_id=%s ORDER BY o.collected_at DESC LIMIT 100''',(topic_id,)).fetchall()
    if not observations:raise HTTPException(409,'topic_observation_missing')
    newest=observations[0]
    # Missing event date is deliberately a review boundary, not an invented event ID.
    event_stamp=newest['trend_started_at'] or newest['collected_at'].astimezone(trends.SCHEDULE_TIMEZONE).date()
    duplicate=hashlib.sha256(f"trend:{topic_id}:{event_stamp}:{blog_id}".encode()).hexdigest()
    contract={'version':'trend-authoring/1','trend_topic_id':str(topic_id),
        'source_observation_ids':[str(o['id']) for o in observations], 'country':topic['representative_geo'],
        'source_language':topic['source_language'],'target_blog_id':str(blog_id),'target_language':blog['language_code'],
        'target_country':blog['target_country'],'query':newest['query'],'query_group':topic['normalized_key'],
        'search_volume_raw':newest['source_volume_label'],'volume_kind':'bucket_lower_bound; not internationally comparable',
        'collected_at':newest['collected_at'].isoformat(),'selection_reason':current['reason'],
        'raw_material':newest['raw_payload'],'duplicate_key':duplicate,'category':category,
        'content_type':'trends_major_issue','requires_codex_evaluation':True,'remote_duplicate_status':'not_checked'}
    row=conn.execute('''INSERT INTO trend_generation_requests(topic_id,duplicate_key,contract)
        VALUES(%s,%s,%s) ON CONFLICT(duplicate_key) DO UPDATE SET duplicate_key=EXCLUDED.duplicate_key RETURNING *''',
        (topic_id,duplicate,Jsonb(contract))).fetchone()
    return dict(row)


def dispatch(limit:int=1) -> dict[str,int]:
    """Convert approved research queues to distinct Codex jobs; never enqueue publication."""
    from . import codex_runner
    created=0
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('trend-codex-dispatch',0))")
        rows=conn.execute("SELECT * FROM trend_generation_requests WHERE state='generation_queued' AND authoring_job_id IS NULL ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s",(limit,)).fetchall()
        for row in rows:
            current=latest(conn,row['topic_id'])
            if not current or current['state']!='generation_queued':continue
            c=row['contract']
            request_key=uuid5(NAMESPACE_URL,'woori-trend-codex:'+str(row['id']))
            options={'keyword':c['query'],'direction':'Research the actual event independently. Trends RSS headlines are unverified context.',
                'category':c['category'],'article_type':'news_analysis','length':'default','research_range':'latest',
                'trend_contract':{'trend_topic_id':c['trend_topic_id'],'observation_ids':c['source_observation_ids'],
                    'selection_reason':c['selection_reason'],'raw_news_items':(c.get('raw_material') or {}).get('news_items',[])[:5]}}
            digest=hashlib.sha256(json.dumps(options,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            job=conn.execute('''INSERT INTO codex_authoring_jobs(request_key,request_sha256,job_type,blog_id,language_code,
              target_country,category,keyword,options,model,trend_request_id)
              VALUES(%s,%s,'google_trends',%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(request_key) DO NOTHING RETURNING id''',
              (request_key,digest,UUID(c['target_blog_id']),c['target_language'],c['target_country'],
               c['category'],c['query'],Jsonb(options),codex_runner.MODEL,row['id'])).fetchone()
            if not job:raise RuntimeError('trend_dispatch_identity_conflict')
            conn.execute("UPDATE trend_generation_requests SET state='generating',authoring_job_id=%s,updated_at=now() WHERE id=%s",(job['id'],row['id']))
            transition(conn,row['topic_id'],'generating','codex_authoring_queued','기존 Codex Runner 조사·원고 작성을 대기합니다.',
                'system:trend-codex-dispatch',category=c['category'],evidence={'authoring_job_id':str(job['id'])})
            created+=1
    return {'created':created}


@router.post('/topics/{topic_id}/decision')
def decision(topic_id:UUID,request:Decision) -> dict[str,Any]:
    with connection() as conn:
        topic=conn.execute('SELECT * FROM trend_topics WHERE id=%s',(topic_id,)).fetchone()
        if not topic:raise HTTPException(404,'topic_not_found')
        if request.category and request.category not in {c['slug'] for c in EDITORIAL_CATEGORIES}:raise HTTPException(422,'unknown_category')
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('trend-editorial:'+str(topic_id),))
        current=latest(conn,topic_id)
        if current and current['state'] in {'generating','imported','published'}:raise HTTPException(409,'existing_authoring_result_must_be_preserved')
        state={'select':'selected','discard':'discarded','reevaluate':'review_candidate','queue':'generation_queued'}[request.action]
        category=request.category or (current['category'] if current else None)
        if request.action=='queue':
            if not request.blog_id:raise HTTPException(422,'target_blog_required')
            row=queue_topic(conn,topic_id,request.blog_id)
            transition(conn,topic_id,state,'operator_queue',request.reason,'authenticated_operator',category=category,key=request.request_key)
            return row
        if request.action=='reevaluate':
            source=conn.execute('''SELECT o.raw_payload FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id
              WHERE m.topic_id=%s ORDER BY o.collected_at DESC LIMIT 1''',(topic_id,)).fetchone()
            state,code,category=classify(topic['representative_query'],source['raw_payload'] if source else None)
        else:code='operator_'+request.action
        if request.action=='discard':
            conn.execute("UPDATE trend_generation_requests SET state='cancelled',updated_at=now() WHERE topic_id=%s AND state='generation_queued' AND authoring_job_id IS NULL",(topic_id,))
        return transition(conn,topic_id,state,code,request.reason,'authenticated_operator',category=category,key=request.request_key)
