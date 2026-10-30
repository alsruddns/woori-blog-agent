"""Audited Trends triage and durable authoring handoff, separate from publication approval."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, HTTPException, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

from . import topics, trends
from .db import connection
from .editorial_taxonomy import EDITORIAL_CATEGORIES

router = APIRouter(prefix='/admin/research/trend-editorial')
STATES = {'collected','pending_classification','selected','review_candidate','discarded',
          'generation_queued','generating','imported','published','failed'}


def current_slot() -> datetime:
    """The active configured Asia/Seoul collection slot."""
    config=trends.collection_settings()
    return trends.configured_slot(datetime.now(UTC),config)


def slot_is_current(value:Any) -> bool:
    try:
        parsed=datetime.fromisoformat(str(value))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None and parsed.astimezone(UTC)==current_slot()
    except (ValueError,TypeError):
        return False


def current_observations(conn:Any,topic_id:UUID) -> list[dict[str,Any]]:
    return [dict(row) for row in conn.execute('''SELECT o.*,s.slot_at FROM trend_topic_memberships m
        JOIN trend_observations o ON o.id=m.observation_id
        JOIN trend_collection_slots s ON s.run_id=o.run_id AND s.geo=o.geo
        WHERE m.topic_id=%s AND s.slot_at=%s ORDER BY o.collected_at DESC LIMIT 100''',
        (topic_id,current_slot())).fetchall()]


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
    news_items=(payload or {}).get('news_items',[])
    headlines=[topics.normalize_query(str(item.get('title') or '')) for item in news_items if isinstance(item,dict)] if isinstance(news_items,list) else []
    query_terms=[token for token in key.split() if len(token)>1]
    relevant=[title for title in headlines if title and (key in title or (query_terms and all(token in title.split() for token in query_terms)))]
    domains=topics.research_domains(query)
    if not domains and relevant:
        # Use a related RSS headline only to choose an existing editorial lane;
        # it remains unverified discovery context, never factual evidence.
        domains=topics.research_domains(' '.join(relevant))
    if not key or key in topics.BROAD_QUERIES:
        return 'discarded','unclear_search_intent',None
    if any(term in key for term in ('rumor','leaked private','사생활','루머','불륜','열애설')):
        return 'discarded','unverifiable_rumor',None
    category=domains[0] if domains else None
    # Feed headlines provide research context, never factual verification.
    # RSS headlines are optional context, not a required prerequisite. The
    # Codex research stage opens current sources and the existing Import gates
    # still keep unsupported claims unverified/held.
    if domains and (len(key)>=5 or bool(relevant)):
        return 'selected','specific_topic_requires_independent_research',category
    return 'review_candidate','insufficient_context',category


class BlogGeoMapping(BaseModel):
    blog_id: UUID
    geo: str = Field(pattern=r'^[A-Z]{2}$')
    enabled: bool
    processing_order: int = Field(ge=1,le=11)


class BlogGeoMappings(BaseModel):
    mappings: list[BlogGeoMapping] = Field(max_length=44)

    @model_validator(mode='after')
    def unique_mappings(self) -> BlogGeoMappings:
        keys=[(row.blog_id,row.geo) for row in self.mappings]
        active_geos=[row.geo for row in self.mappings if row.enabled]
        active_orders=[(row.blog_id,row.processing_order) for row in self.mappings if row.enabled]
        if len(set(keys))!=len(keys) or len(set(active_geos))!=len(active_geos) or len(set(active_orders))!=len(active_orders):
            raise ValueError('duplicate_trend_blog_geo_mapping')
        return self


@router.get('/blog-geos')
def get_blog_geo_mappings() -> dict[str,Any]:
    from .keyword_jobs import targets
    with connection() as conn:
        blogs=targets(conn)
        mappings=conn.execute('''SELECT blog_id,geo,enabled,processing_order,created_at,updated_at
            FROM trend_blog_geo_authoring ORDER BY blog_id,processing_order,geo''').fetchall()
    return {'blogs':blogs,'geos':sorted(trends.ALLOWED_GEOS),'mappings':mappings,
            'same_geo_multiple_blogs':False,'source_geo_is_not_blog_locale_or_publication_country':True}


@router.put('/blog-geos')
def put_blog_geo_mappings(request:BlogGeoMappings) -> dict[str,Any]:
    from psycopg.types.json import Jsonb

    from .keyword_jobs import targets
    if any(row.geo not in trends.ALLOWED_GEOS for row in request.mappings):
        raise HTTPException(422,'trend_geo_not_allowlisted')
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('trend-blog-geo-authoring',0))")
        allowed={row['id']:row for row in targets(conn)}
        if any(row.blog_id not in allowed for row in request.mappings):
            raise HTTPException(409,'active_blog_locale_country_policy_required')
        before=conn.execute('''SELECT blog_id,geo,enabled,processing_order FROM trend_blog_geo_authoring
            ORDER BY blog_id,geo FOR UPDATE''').fetchall()
        # Free active ordering/geo indexes before applying a reordered set.
        conn.execute('UPDATE trend_blog_geo_authoring SET enabled=false,updated_at=now() WHERE enabled')
        for row in request.mappings:
            conn.execute('''INSERT INTO trend_blog_geo_authoring(blog_id,geo,enabled,processing_order)
                VALUES(%s,%s,%s,%s) ON CONFLICT(blog_id,geo) DO UPDATE SET enabled=EXCLUDED.enabled,
                processing_order=EXCLUDED.processing_order,updated_at=now()''',
                (row.blog_id,row.geo,row.enabled,row.processing_order))
        after=conn.execute('''SELECT blog_id,geo,enabled,processing_order FROM trend_blog_geo_authoring
            ORDER BY blog_id,geo''').fetchall()
        before_json=[{**dict(r),'blog_id':str(r['blog_id'])} for r in before]
        after_json=[{**dict(r),'blog_id':str(r['blog_id'])} for r in after]
        if before_json!=after_json:
            conn.execute("INSERT INTO audit_events(event_type,payload) VALUES('trend.authoring.geo_mappings_changed',%s)",
                (Jsonb({'before':before_json,'after':after_json,'actor':'authenticated_operator',
                        'publication_authority_changed':False}),))
    return get_blog_geo_mappings()


def reconcile(limit: int = 200) -> dict[str,int]:
    """Bounded backlog, existing exact-query groups; no lexical cross-language auto merges."""
    slot=current_slot()
    with connection() as conn:
        # Expire only candidates which have not started authoring. Never delete
        # observations or overwrite prior editorial/audit records.
        stale=conn.execute('''SELECT t.id,e.category FROM trend_topics t
            JOIN LATERAL(SELECT * FROM trend_editorial_events WHERE topic_id=t.id ORDER BY id DESC LIMIT 1)e ON true
            WHERE e.state IN ('selected','review_candidate','pending_classification','collected')
              AND (e.created_at<%s OR NOT EXISTS(SELECT 1 FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id
                JOIN trend_collection_slots s ON s.run_id=o.run_id AND s.geo=o.geo
                WHERE m.topic_id=t.id AND s.slot_at=%s))
            ORDER BY e.id LIMIT %s''',(slot,slot,limit)).fetchall()
        for item in stale:
            transition(conn,item['id'],'discarded','expired_collection_slot',
                '이전 회차의 미처리 후보가 만료되었습니다. 원본 관측과 이력은 보존합니다.',
                'system:trend-slot',category=item['category'],evidence={'current_slot':slot.isoformat()})
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
            JOIN LATERAL(SELECT o.raw_payload,o.collected_at FROM trend_topic_memberships m JOIN trend_observations o ON o.id=m.observation_id
              JOIN trend_collection_slots s ON s.run_id=o.run_id AND s.geo=o.geo
              WHERE m.topic_id=t.id AND s.slot_at=%s ORDER BY o.collected_at DESC LIMIT 1)o ON true
            LEFT JOIN LATERAL(SELECT id,state,actor,created_at,reason_code FROM trend_editorial_events e
              WHERE e.topic_id=t.id ORDER BY id DESC LIMIT 1)e ON true
            WHERE e.id IS NULL OR (e.state='review_candidate' AND e.actor='system:trend-editorial-v1'
              AND o.collected_at>e.created_at AND o.raw_payload IS NOT NULL)
              OR (e.state='discarded' AND e.reason_code='expired_collection_slot')
            ORDER BY t.created_at DESC LIMIT %s''',(slot,limit)).fetchall()
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
        blog_geo_mappings=conn.execute('''SELECT blog_id,geo,enabled,processing_order FROM trend_blog_geo_authoring
            WHERE enabled ORDER BY blog_id,processing_order,geo''').fetchall()
    return {'items':items,'total':total,'page':page,'page_size':page_size,'summary':summary,'blogs':blogs,
            'blog_geo_mappings':blog_geo_mappings,
            'geos':sorted(trends.ALLOWED_GEOS),'categories':list(EDITORIAL_CATEGORIES),
            'summary_unit':'observations; one topic may have many observations',
            'schedule':f"KST every {trends.collection_settings()['interval_minutes']} minutes; current-slot data only"}


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


def queue_topic(conn:Any,topic_id:UUID,blog_id:UUID,*,selection_rank:int|None=None,
                processing_order:int|None=None) -> dict[str,Any]:
    from .keyword_jobs import targets
    current=latest(conn,topic_id)
    if not current or current['state'] not in {'selected','generation_queued'}:raise HTTPException(409,'topic_not_selected')
    if current['created_at']<current_slot():raise HTTPException(409,'expired_collection_slot')
    topic=conn.execute('SELECT * FROM trend_topics WHERE id=%s',(topic_id,)).fetchone()
    blog=next((b for b in targets(conn) if b['id']==blog_id),None)
    mapping=conn.execute('''SELECT 1 FROM trend_blog_geo_authoring
        WHERE blog_id=%s AND geo=%s AND enabled''',(blog_id,topic['representative_geo'])).fetchone()
    if not blog or not mapping:
        raise HTTPException(409,'enabled_trend_blog_geo_mapping_required')
    category=current['category']
    if category not in {c['slug'] for c in EDITORIAL_CATEGORIES}:raise HTTPException(409,'editorial_category_required')
    observations=current_observations(conn,topic_id)
    if not observations:raise HTTPException(409,'expired_collection_slot')
    newest=observations[0]
    # Missing event date is deliberately a review boundary, not an invented event ID.
    event_stamp=newest['trend_started_at'] or newest['collected_at'].astimezone(trends.SCHEDULE_TIMEZONE).date()
    duplicate=hashlib.sha256(f"trend:{topic_id}:{event_stamp}:{blog_id}".encode()).hexdigest()
    previous=conn.execute('''SELECT q.id FROM trend_generation_requests q JOIN trend_topics prior ON prior.id=q.topic_id
        WHERE prior.normalized_key=%s AND q.contract->>'target_blog_id'=%s AND q.duplicate_key<>%s LIMIT 1''',
        (topic['normalized_key'],str(blog_id),duplicate)).fetchone()
    if previous:raise HTTPException(409,'topic_already_requested_for_blog')
    contract={'version':'trend-authoring/2','trend_topic_id':str(topic_id),
        'source_observation_ids':[str(o['id']) for o in observations], 'country':topic['representative_geo'],
        'source_country':topic['representative_geo'],
        'source_language':topic['source_language'],'target_blog_id':str(blog_id),'target_language':blog['language_code'],
        'target_country':blog['target_country'],'query':newest['query'],'query_group':topic['normalized_key'],
        'search_volume_raw':newest['source_volume_label'],'volume_kind':'bucket_lower_bound; not internationally comparable',
        'collected_at':newest['collected_at'].isoformat(),'collection_slot':newest['slot_at'].isoformat(),
        'selection_reason':current['reason'],
        'raw_material':newest['raw_payload'],'duplicate_key':duplicate,'category':category,
        'selection_rank':selection_rank,'processing_order':processing_order,
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
            if not slot_is_current(c.get('collection_slot')) or not current_observations(conn,row['topic_id']):
                conn.execute("UPDATE trend_generation_requests SET state='cancelled',updated_at=now() WHERE id=%s",(row['id'],))
                transition(conn,row['topic_id'],'discarded','expired_collection_slot','이전 수집 회차의 미실행 작성 요청을 만료했습니다.',
                           'system:trend-slot',evidence={'generation_request_id':str(row['id'])})
                continue
            request_key=uuid5(NAMESPACE_URL,'woori-trend-codex:'+str(row['id']))
            options={'keyword':c['query'],'direction':
                'Write an original article for readers of the selected Blogger language. Directly research why this Google Trends query is active now using live web search; no pre-collected news URL is required. Prioritize primary sources and reputable reporting, verify each material claim, date, number, and quotation, and reject rumor or unsupported interpretation. Trends popularity and RSS headlines are discovery context only, not evidence. If no current verifiable event or useful article can be established, return an insufficient-evidence failure instead of inventing a story.',
                'category':c['category'],'article_type':'news_analysis','length':'default','research_range':'latest',
                'trend_contract':{'trend_topic_id':c['trend_topic_id'],'observation_ids':c['source_observation_ids'],
                    'source_country':c['source_country'],'target_country':c['target_country'],
                    'target_blog_id':c['target_blog_id'],'target_language':c['target_language'],
                    'search_volume_raw':c['search_volume_raw'],'collection_slot':c['collection_slot'],
                    'selection_rank':c.get('selection_rank'),'processing_order':c.get('processing_order'),
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


def queue_selected() -> dict[str,int]:
    """Queue current-slot candidates by country rank using explicit blog mappings."""
    from .config import settings
    from .keyword_jobs import targets
    slot=current_slot()
    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('trend-selected-queue',0))")
        limit=settings().trend_research_hourly_limit
        recent=conn.execute('SELECT count(*) n FROM trend_generation_requests WHERE created_at>=now()-interval \'1 hour\'').fetchone()
        remaining=max(0,limit-int(recent['n'] if recent else 0))
        if not remaining:return {'created':0,'hourly_capacity':limit}
        mappings=conn.execute('''SELECT m.blog_id,m.geo,m.processing_order,b.display_name
            FROM trend_blog_geo_authoring m JOIN blogger_blogs b ON b.id=m.blog_id
            WHERE m.enabled AND b.active AND b.blog_id IS NOT NULL
            ORDER BY m.blog_id,m.processing_order,m.geo''').fetchall()
        blogs={b['id']:b for b in targets(conn)}
        # Rotate each blog's starting geography by collection slot so a fixed
        # ordering cannot starve the last country in a multi-country mapping.
        by_blog:dict[UUID,list[dict[str,Any]]]={}
        for row in mappings:by_blog.setdefault(row['blog_id'],[]).append(dict(row))
        interval=int(trends.collection_settings()['interval_minutes'])
        epoch=int(slot.timestamp()//(interval*60))
        ordered=[]
        for blog_id,items in sorted(by_blog.items(),key=lambda pair:str(pair[0])):
            offset=epoch%len(items) if items else 0
            ordered.extend(items[offset:]+items[:offset])
        created=0
        for mapping in ordered:
            if created>=remaining:break
            blog=blogs.get(mapping['blog_id'])
            if not blog:continue
            already=conn.execute('''SELECT count(*) n, bool_or(state IN ('generation_queued','generating','imported')) active
                FROM trend_generation_requests WHERE contract->>'source_country'=%s
                  AND contract->>'target_blog_id'=%s AND (contract->>'collection_slot')::timestamptz=%s''',
                (mapping['geo'],str(mapping['blog_id']),slot.isoformat())).fetchone()
            if already and (already['active'] or already['n']>=3):continue
            rows=conn.execute('''SELECT t.id,t.representative_query,t.normalized_key,t.source_language,
                    o.source_volume_lower_bound,o.source_volume_label,o.trend_started_at,o.collected_at,o.raw_payload,
                    e.state,e.category,e.reason_code
                FROM trend_topics t
                JOIN trend_topic_memberships m ON m.topic_id=t.id
                JOIN trend_observations o ON o.id=m.observation_id AND o.geo=%s
                JOIN trend_collection_slots s ON s.run_id=o.run_id AND s.geo=o.geo AND s.slot_at=%s
                LEFT JOIN LATERAL(SELECT state,category,reason_code FROM trend_editorial_events
                    WHERE topic_id=t.id ORDER BY id DESC LIMIT 1)e ON true
                WHERE o.source_volume_lower_bound IS NOT NULL AND o.source_volume_lower_bound>0
                  AND o.trend_started_at IS NOT NULL
                  AND NOT EXISTS(SELECT 1 FROM trend_generation_requests q JOIN trend_topics prior ON prior.id=q.topic_id
                    WHERE prior.normalized_key=t.normalized_key AND q.contract->>'target_blog_id'=%s)
                ORDER BY o.source_volume_lower_bound DESC,o.trend_started_at DESC,o.collected_at DESC,t.id LIMIT 100''',
                (mapping['geo'],slot,str(mapping['blog_id']))).fetchall()
            for rank,row in enumerate(rows,1):
                state,code,category=classify(row['representative_query'],row['raw_payload'])
                if state!='selected' or not (row['category'] or category):continue
                category=row['category'] or category
                current=latest(conn,row['id'])
                if not current or current['state'] in {'review_candidate','pending_classification','collected'}:
                    transition(conn,row['id'],'selected',code,
                        '현재 수집 회차의 검색량·최신성·주제 적합성으로 Codex 독립 조사를 선정했습니다. 근거나 사실 승인으로 간주하지 않습니다.',
                        'system:trend-country-rank',category=category,evidence={'geo':mapping['geo'],
                        'volume_lower_bound':row['source_volume_lower_bound'],'trend_started_at':row['trend_started_at'].isoformat(),
                        'collection_slot':slot.isoformat(),'rank_basis':'within_geo_volume_desc_then_started_desc'})
                queued=queue_topic(conn,row['id'],mapping['blog_id'],selection_rank=rank,
                                   processing_order=mapping['processing_order'])
                transition(conn,row['id'],'generation_queued','automatic_country_rank_queue',
                    '국가별 검색량 내림차순 후보를 공통 Codex Runner의 웹 조사 큐로 전달했습니다.',
                    'system:trend-slot',category=category,evidence={'generation_request_id':str(queued['id']),
                    'geo':mapping['geo'],'blog_id':str(mapping['blog_id']),'processing_order':mapping['processing_order']})
                created+=1
                break
        return {'created':created,'hourly_capacity':limit}


def expire_pending(limit:int=100) -> int:
    """Expire only queued, never-started authoring requests under row locks."""
    from .keyword_jobs import update
    count=0
    with connection() as conn:
        rows=conn.execute('''SELECT q.id,q.topic_id,q.contract,j.id job_id,j.execution_id
            FROM trend_generation_requests q JOIN codex_authoring_jobs j ON j.id=q.authoring_job_id
            WHERE q.state='generating' AND j.state='queued' AND j.execution_id IS NULL
            ORDER BY q.created_at FOR UPDATE OF q,j SKIP LOCKED LIMIT %s''',(limit,)).fetchall()
        for row in rows:
            if slot_is_current(row['contract'].get('collection_slot')) and current_observations(conn,row['topic_id']):continue
            update(conn,row['job_id'],'cancelled',error_code='expired_collection_slot',completed_at=datetime.now(UTC))
            conn.execute("UPDATE trend_generation_requests SET state='cancelled',updated_at=now() WHERE id=%s",(row['id'],))
            transition(conn,row['topic_id'],'discarded','expired_collection_slot',
                '수집 회차가 끝나 실행되지 않은 작성 요청을 만료했습니다.',
                'system:trend-slot',evidence={'authoring_job_id':str(row['job_id'])})
            count+=1
    return count


@router.post('/topics/{topic_id}/decision')
def decision(topic_id:UUID,request:Decision) -> dict[str,Any]:
    with connection() as conn:
        topic=conn.execute('SELECT * FROM trend_topics WHERE id=%s',(topic_id,)).fetchone()
        if not topic:raise HTTPException(404,'topic_not_found')
        if request.category and request.category not in {c['slug'] for c in EDITORIAL_CATEGORIES}:raise HTTPException(422,'unknown_category')
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('trend-editorial:'+str(topic_id),))
        current=latest(conn,topic_id)
        if current and current['state'] in {'generating','imported','published'}:raise HTTPException(409,'existing_authoring_result_must_be_preserved')
        if request.action in {'select','reevaluate','queue'} and not current_observations(conn,topic_id):
            raise HTTPException(409,'expired_collection_slot')
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
