"use client";
import { useState, type FormEvent } from "react";
import ManuscriptManager from "./manuscript-manager";

type Row = Record<string, unknown>;
export type State = {
  profiles: Row[]; categories: Row[]; keywords: Row[]; sources: Row[]; jobs: Row[];
  versions: Row[]; settings: Row[]; prompts: Row[]; controls: Row; schedules: Row[];
  attempts: Row[]; events: Row[]; dispatches: Row[]; collection_sources: Row[]; cost_policy?: Row;
  collection_jobs: Row[]; measurements: Row[]; stage_runs: Row[]; coverage: Row[]; experiments?: Row[];
  trend_sources?: Row[]; trend_collection_runs?: Row[]; trend_observations?: Row[];
  trend_collection_configured?: boolean;
  trend_topics?: Row[]; trend_grouping_proposals?: Row[]; trend_research_packages?: Row[]; trend_topic_sources?: Row[];
  trend_scoring_config?: Row | null;
  trend_topic_workspace_configured?: boolean;
  evidence_facts?: Row[]; localizations?: Row[]; glossary?: Row[]; glossary_revisions?: Row[];
  article_evaluations?: Row[]; worker?: Row | null; evaluation_worker?: Row | null; daily_workload?: Row[]; operations_summary?: Row;
  manuscript_publications?: Row[];
  manuscript_publication_records?: Row[];
  evaluation_results?: { configured?: boolean; available?: boolean; database?: string; baseline_snapshot_at?: string; error_category?: string; worker?: Row | null; quota?: Row[]; runs?: Row[]; stages?: Row[]; events?: Row[]; fed_articles?: Row[]; editorial_articles?: Row[]; sec_historical_quality?: Row[]; sec_new_inference?: string; sec_locale_availability?: Row[]; sec_source_draft_available?: boolean; sec_english_quota_reservation?: Row };
  adsense_readiness?: { captured_at?: string; approval_prediction?: string; blogs?: Row[]; internal_recommendations?: Row; official_references?: string[] };
  prepublication?: { blogs?: Row[]; blogger_accounts_connected?: number; historical_read_verifications?: Row[]; safety?: Row; real_blogger_sync_verified?: boolean; real_writes_enabled?: boolean };
  article_reviews?: Row[];
  article_review_events?: Row[];
  article_editorial_versions?: Row[];
  publication_approval_events?: Row[];
  operational_readiness?: { captured_from?: string; items?: { key: string; status: string; evidence: unknown }[] };
};
type Field = { name: string; label: string; type?: string; optional?: boolean; options?: { value: string; label: string }[] };
const str = (row: Row, key: string) => String(row[key] ?? "");
const profileLabel = (p: Row) => `${str(p, "language_code")} / ${str(p, "target_country") || "국가 미지정"}`;

function Editor({ fields, defaults = {}, submit, label, disabled }: {
  fields: Field[]; defaults?: Row; submit: (data: Row) => Promise<void>; label: string; disabled: boolean;
}) {
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget), output: Row = {};
    for (const f of fields) {
      const value = String(form.get(f.name) ?? "");
      output[f.name] = f.type === "checkbox" ? form.has(f.name) : f.type === "number" ? Number(value)
        : f.type === "datetime-local" ? (value ? new Date(value).toISOString() : null) : value;
    }
    void submit(output);
  }
  return <form onSubmit={save}>{fields.map(f => <label key={f.name}>{f.label} {f.options
    ? <select name={f.name} defaultValue={str(defaults, f.name)} required>{f.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
    : f.type === "textarea" ? <textarea name={f.name} defaultValue={str(defaults, f.name)} required={!f.optional}/>
    : <input name={f.name} type={f.type ?? "text"} defaultValue={f.type === "checkbox" ? undefined : str(defaults, f.name)} defaultChecked={f.type === "checkbox" ? Boolean(defaults[f.name]) : undefined} required={f.type !== "checkbox" && !f.optional}/>}
  </label>)}<button disabled={disabled}>{label}</button></form>;
}

export default function Research({ initial }: { initial: State }) {
  const [data, setData] = useState(initial), [local, setLocal] = useState<Row>({}), [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(""), [left, setLeft] = useState(""), [right, setRight] = useState("");
  const [measureLeft, setMeasureLeft] = useState(""), [measureRight, setMeasureRight] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("");
  async function refresh() {
    const [state, ai] = await Promise.all([fetch("/api/research/state", { cache: "no-store" }), fetch("/api/research/local-ai", { cache: "no-store" })]);
    if (!state.ok || !ai.ok) throw new Error("상태 조회 실패");
    setData(await state.json() as State); setLocal(await ai.json() as Row);
  }
  async function act(path: string, body: Row, method = "POST") {
    setBusy(true);
    try {
      const response = await fetch(`/api/research/${path}`, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await response.json() as Row;
      if (!response.ok) throw new Error(String(value.error ?? JSON.stringify(value.detail ?? "요청 실패")));
      setMessage(path === "publication-approvals"
        ? "발행 의사 기록을 저장했습니다. 실제 게시·예약 실행은 계속 차단되어 있습니다."
        : "저장했습니다. 대기 작업은 Worker가 처리합니다."); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "요청 실패"); } finally { setBusy(false); }
  }
  const profiles = data.profiles.filter(p => p.active).map(p => ({ value: str(p, "id"), label: profileLabel(p) }));
  const categories = data.categories.map(c => ({ value: str(c, "id"), label: str(c, "slug") }));
  const promptOptions = data.prompts.map(p => ({ value: str(p, "id"), label: `${str(p, "name")} v${str(p, "version")}` }));
  const profileField: Field = { name: "profile_id", label: "원본 언어·국가", options: profiles };
  const categoryField: Field = { name: "category_id", label: "카테고리", options: categories };
  const versions = [data.versions.find(v => v.id === left), data.versions.find(v => v.id === right)];
  const measurements = [data.measurements.find(m => m.id === measureLeft), data.measurements.find(m => m.id === measureRight)];
  const experiments = data.experiments ?? [];
  const currentExperimentId = experiments[0]?.experiment_id;
  const currentExperiments = experiments.filter(item => item.experiment_id === currentExperimentId);
  const c3ModelComparisons = (data.evaluation_results?.runs ?? []).filter(run => run.sec_source || run.fed_source)
    .reduce<Record<string, Row[]>>((groups, run) => {
      const source = run.sec_source ? "SEC" : "Federal Reserve";
      const key = `${source}:${str(run, "keyword_id")}:${str(run, "language_code")}`;
      (groups[key] ??= []).push(run);
      return groups;
    }, {});
  const experimentFailureCounts = currentExperiments.reduce<Record<string, number>>((counts, item) => {
    const checks = (item.checks as Row | undefined)?.grounding as Row | undefined;
    const ruleChecks = (checks?.rule_checks as Row | undefined) ?? {};
    for (const [name, passed] of Object.entries(ruleChecks)) if (passed === false) counts[name] = (counts[name] ?? 0) + 1;
    const structure = (item.checks as Row | undefined)?.structure as Row | undefined;
    const structureChecks = (structure?.checks as Row | undefined) ?? {};
    for (const [name, passed] of Object.entries(structureChecks)) if (passed === false) counts[name] = (counts[name] ?? 0) + 1;
    return counts;
  }, {});
  const unlinkedEvidenceCount = currentExperiments.filter(item => {
    const checks = (item.checks as Row | undefined)?.grounding as Row | undefined;
    const rules = (checks?.rule_checks as Row | undefined) ?? {};
    return rules.citation_ids_valid !== true || rules.factual_paragraphs_cited !== true;
  }).length;
  return <>
    <section><h2>무인 작업 운영 상태</h2>
      <p>Worker: {data.worker?.fresh ? str(data.worker, "status") : "heartbeat 미확인 또는 45초 이상 오래됨"} · 마지막 확인 {str(data.worker ?? {}, "last_seen_at") || "기록 없음"}</p>
      {data.worker?.last_error_category ? <p role="alert">최근 Worker 오류 분류: {str(data.worker, "last_error_category")}</p> : null}
      <p>발행은 계속 차단되어 있고, 기계 품질 통과도 사람 검토 승인을 대신하지 않습니다.</p>
      <details><summary>실제 DB 작업·초안·품질 집계</summary><pre>{JSON.stringify(data.operations_summary ?? {}, null, 2)}</pre></details>
    </section>
    <section><h2>근거 우선 A/B 평가</h2>
      <p>저장된 Phase 3.7 원고 재평가와 사실 고정 템플릿 실험입니다. 규칙 검사 결과와 사람 검토 대기를 구분하며, 발행 준비는 항상 false입니다.</p>
      <p>최신 비교 평가 품질 보류: {currentExperiments.filter(e => !e.mechanical_gate_passed).length}건 · 사람 검토 대기: {currentExperiments.filter(e => e.human_review_required).length}건 · 근거 연결 실패: {unlinkedEvidenceCount}건</p>
      <p>실패 사유별 건수: {Object.entries(experimentFailureCounts).map(([name, count]) => `${name} ${count}`).join(" · ") || "없음"}</p>
      {experiments.map(e => <details key={str(e, "id")}><summary>{str(e, "language")} · {str(e, "variant")} · {e.mechanical_gate_passed ? "규칙 게이트 통과" : "품질 보류"} · {str(e, "created_at")}</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify({ experiment_id: e.experiment_id, source_version: e.content_version_id, processing: e.metrics, checks: e.checks, publish_ready: e.publish_ready, output: e.output_snapshot }, null, 2)}</pre></details>)}
    </section>
    <section><h2>Zero additional cost policy</h2><p>External gate: {data.cost_policy?.external_calls_allowed ? "active; check provider-specific blocks" : "blocked by credential or terms review"}</p><p>Paid fallback and automatic paid upgrades are disabled.</p><details><summary>?? ?? ?? ?? JSON</summary><pre>{JSON.stringify({ blockedProviders: data.cost_policy?.blocked_providers ?? [], credentialNames: data.cost_policy?.blocked_credential_names ?? [] }, null, 2)}</pre></details></section>
    <p role="status">{message}</p><button disabled={busy} onClick={() => refresh().catch(() => setMessage("조회 실패"))}>새로 고침</button>
    <section><h2>실제 로컬 AI 상태·성능 측정</h2>
      <p>연결 상태: {local.available ? "정상" : "미연결 또는 로딩 중"} · 현재 모델: {str(local, "model") || "확인 전"}</p>
      <p>실행 백엔드: {str(local, "backend") === "vulkan" ? `Vulkan · 요청 layer ${str(local, "gpu_layers") || "0"}` : "CPU 전용"} · GPU Engine 사용률은 측정 행에 실제 값이 있을 때만 표시합니다. 성능 측정 성공은 사실·번역 품질 합격을 뜻하지 않습니다.</p>
      <details><summary>설치 모델·버전·해시</summary><pre>{JSON.stringify(local.installed_models ?? [], null, 2)}</pre></details>
      {data.measurements.map(m => <details key={str(m, "id")}><summary>{str(m, "model")} · {str(m, "language_code")} · {str(m, "status")} · {str(m, "error_category")}</summary>
        <pre>{JSON.stringify({ checks: m.checks, metrics: m.metrics, sample: m.sample }, null, 2)}</pre></details>)}
      <h3>실측 모델 결과 나란히 비교</h3>
      {[{ id: measureLeft, set: setMeasureLeft }, { id: measureRight, set: setMeasureRight }].map((item, index) => <label key={index}>모델 결과 {index + 1}<select value={item.id} onChange={e => item.set(e.target.value)}><option value="">측정 결과 선택</option>{data.measurements.map(m => <option key={str(m, "id")} value={str(m, "id")}>{str(m, "model")} · {str(m, "language_code")} · {str(m, "status")}</option>)}</select></label>)}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 20 }}>{measurements.map((m, index) => m && <article key={index}><h4>{str(m, "model")} · {str(m, "language_code")}</h4><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify({ status: m.status, error: m.error_category, checks: m.checks, metrics: m.metrics, generated_sample: m.sample }, null, 2)}</pre></article>)}</div>
    </section>
    <section><h2>자동 주제 수집·근거 자료 조사</h2>
      <article aria-labelledby="trend-collection">
        <h3 id="trend-collection">국가별 Google Trends RSS</h3>
        <p>공식 도움말이 RSS 내보내기를 안내합니다. 이 피드는 검색어 목록이며, 제공자가 순위를 명시하지 않으므로 순위는 미수집으로 저장합니다. 검색량은 원천의 구간 표기만 보존합니다.</p>
        <p>대상 지역: KR, US, JP, TW, HK, SG. 중국 본토는 Google Trends 제공 지역으로 간주하지 않습니다. 자동 스케줄은 비활성 상태이며 아래 실행은 선택한 지역 1회 수집입니다.</p>
        {!data.trend_collection_configured && <p role="status">추세 저장 스키마가 아직 운영 DB에 적용되지 않아 수집은 비활성화되어 있습니다.</p>}
        {data.trend_sources?.map(source => <p key={str(source, "endpoint")}>{str(source, "policy")} · 시간당 앱 제한 {str(source, "hourly_limit")}</p>)}
        {(["KR", "US", "JP", "TW", "HK", "SG"] as const).map(geo => <button key={geo} disabled={busy || !data.trend_collection_configured} onClick={() => void act("trends/collect", { geo })}>{geo} 트렌드 1회 수집</button>)}
        <details><summary>최근 수집 실행 원본 데이터</summary><pre>{JSON.stringify(data.trend_collection_runs ?? [], null, 2)}</pre></details>
        <details><summary>저장 검색어 원본 데이터 (최대 300건)</summary><pre>{JSON.stringify(data.trend_observations ?? [], null, 2)}</pre></details>
        <h4>주제 후보 그룹화 및 게시 가치 평가</h4>
        <p>같은 지역의 정규화된 동일 검색어만 묶습니다. 지역 간 유사 검색어는 사건 동일성을 확인할 수 없어 검토 제안으로만 남깁니다. 자동 선택·게시 승인 기능은 없습니다.</p>
        {!data.trend_topic_workspace_configured && <p role="status">주제 및 자료 패키지 스키마가 적용되지 않았습니다.</p>}
        {data.trend_scoring_config && <>
          <p>Scoring rubric v{str(data.trend_scoring_config, "version")}: weights and conservative evidence thresholds are versioned in the database. Thresholds cannot be lowered below the safety baseline. Scores do not approve content.</p>
          <details><summary>?? ?? ?? JSON</summary><pre>{JSON.stringify(data.trend_scoring_config, null, 2)}</pre></details>
          <Editor disabled={busy} label="Create scoring rubric version" defaults={data.trend_scoring_config.weights as Row}
            fields={[...(["source_interest_label", "freshness", "specificity", "reviewed_source_coverage", "independent_confirmation", "deduplication_risk"].map(name => ({ name, label: name, type: "number" }))), { name: "rationale", label: "Change rationale", type: "textarea" }]}
            submit={body => { const { rationale, ...weights } = body; return act("topics/scoring-configs", {
              weights, thresholds: data.trend_scoring_config?.thresholds ?? {}, rationale,
            }); }}/>
        </>}
        <button disabled={busy || !data.trend_topic_workspace_configured} onClick={() => void act("topics/build", {})}>최근 7일 주제 그룹화 및 평가</button>
        {(data.trend_topics ?? []).map(topic => {
          const assessment = (topic.latest_assessment as Row | null) ?? {};
          const editorial = (topic.latest_editorial_decision as Row | null) ?? {};
          const pack = (topic.latest_package as Row | null) ?? {};
          const observations = (topic.observations as Row[] | null) ?? [];
          const topicSourceLinks = (data.trend_topic_sources ?? []).filter(link => link.topic_id === topic.id);
          const reviewedSourceOptions = data.sources.filter(source => source.approved === true).map(source => ({ value: str(source, "id"), label: `${str(source, "source_name")} · ${str(source, "url")}` }));
          return <article key={str(topic, "id")}>
            <h5>{str(topic, "representative_query")} · {str(topic, "representative_geo")} · {str(assessment, "decision") || "미평가"}</h5>
            <p>Topic ID {str(topic, "id")} · 언어 {str(topic, "source_language")} · 그룹 방식 {str(topic, "grouping_method")} · 신뢰도 {str(topic, "grouping_confidence")} · 사건 동일성 확정 여부: 아니오</p>
            <p>평가 점수 {str(assessment, "score") || "미평가"}/100 · 검토 판단 {str(editorial, "decision") || "대기"} · 사람 검토 필수</p>
            {Array.isArray(assessment.reasons) && <p>보류·검토 사유: {(assessment.reasons as string[]).join(" · ")}</p>}
            <button disabled={busy} onClick={() => void act(`topics/${str(topic, "id")}/assess`, {})}>현재 근거로 재평가</button>
            <button disabled={busy} onClick={() => void act(`topics/${str(topic, "id")}/package`, {})}>근거 패키지 생성</button>
            <Editor disabled={busy} label="주제 선정·보류·제외 결정 기록" defaults={{ decision: "hold", reviewer: "", reason: "" }}
              fields={[{ name: "decision", label: "편집 판단", options: [{ value: "selected", label: "선정" }, { value: "hold", label: "보류" }, { value: "excluded", label: "제외" }] }, { name: "reviewer", label: "검토자" }, { name: "reason", label: "사유", type: "textarea" }]}
              submit={body => act(`topics/${str(topic, "id")}/decisions`, { ...body, idempotency_key: crypto.randomUUID() })}/>
            <Editor disabled={busy || reviewedSourceOptions.length === 0} label="기존 승인·근거 검증된 출처 연결" defaults={{ link_reason: "", linked_by: "" }}
              fields={[{ name: "source_id", label: "승인된 출처", options: reviewedSourceOptions }, { name: "link_reason", label: "주제 관련성 사유" }, { name: "linked_by", label: "연결자" }]}
              submit={body => act(`topics/${str(topic, "id")}/sources`, { ...body, idempotency_key: crypto.randomUUID() })}/>
            {topicSourceLinks.map(link => <div key={str(link, "id")}>
              <p>출처: {str(link, "source_name")} · 사실 {str(link, "verified_fact_count")}건 · 승인 {String(link.latest_approved ?? false)} · 독립성 {str(link, "independence_decision") || "미검토"}</p>
              <Editor disabled={busy} label="출처 독립성 검토 기록" defaults={{ decision: "uncertain", reviewer: "", reason: "", comparison_group: "" }}
                fields={[{ name: "decision", label: "독립성", options: [{ value: "independent", label: "독립 출처" }, { value: "same_underlying_source", label: "동일 원출처" }, { value: "uncertain", label: "불확실" }] }, { name: "reviewer", label: "검토자" }, { name: "reason", label: "비교 근거", type: "textarea" }, { name: "comparison_group", label: "비교 그룹", optional: true }]}
                submit={body => act(`topic-sources/${str(link, "id")}/independence-reviews`, { ...body, idempotency_key: crypto.randomUUID() })}/>
            </div>)}
            <p>관측 {observations.length}건 · 관련 교차지역 그룹화 제안 {str(topic, "grouping_proposal_count")}건</p>
            <details><summary>검색어 관측과 원천 자료</summary><pre>{JSON.stringify(observations, null, 2)}</pre></details>
            <details><summary>최신 게시 가치 평가</summary><pre>{JSON.stringify(assessment, null, 2)}</pre></details>
            <details><summary>최신 Research Package</summary><pre>{JSON.stringify(pack, null, 2)}</pre></details>
          </article>;
        })}
        <h4>사건 동일성 검토 제안</h4>{(data.trend_grouping_proposals ?? []).map(proposal => {
          const leftObservation = (proposal.left_observation as Row | null) ?? {};
          const rightObservation = (proposal.right_observation as Row | null) ?? {};
          const latestReview = (proposal.latest_review as Row | null) ?? {};
          return <article key={str(proposal, "id")}>
            <p>{str(leftObservation, "geo")} ? {str(leftObservation, "query")} ? {str(rightObservation, "geo")} ? {str(rightObservation, "query")}</p>
            <p>{str(proposal, "method")} ? confidence {str(proposal, "confidence")} ? {str(proposal, "rationale")}</p>
            <p>Review: {str(latestReview, "decision") || "pending"} ? event group {str(latestReview, "event_group_id") || "unassigned"}</p>
            <Editor disabled={busy} label="Record grouping review" defaults={{ decision: "insufficient_information", reviewer: "", rationale: "", event_group_id: "" }}
              fields={[
                { name: "decision", label: "Decision", options: [
                  { value: "same_event", label: "Same event" },
                  { value: "different_event", label: "Different events" },
                  { value: "insufficient_information", label: "Insufficient information" },
                ] },
                { name: "event_group_id", label: "Event group UUID (required for same event)", optional: true },
                { name: "reviewer", label: "Reviewer" },
                { name: "rationale", label: "Evidence and rationale", type: "textarea" },
              ]}
              submit={body => act(`grouping-proposals/${str(proposal, "id")}/reviews`, { ...body, idempotency_key: crypto.randomUUID() })}/>
          </article>;
        })}
        <details><summary>Research Package 이력 JSON</summary><pre>{JSON.stringify(data.trend_research_packages ?? [], null, 2)}</pre></details>
      </article>
      <p>Fed·SEC 공식 자료와 Wikidata CC0 구조화 메타데이터만 허용합니다. Wikidata 후보는 공식 발표·시세·영업·효능 검증 자료가 아니며 승인 대기입니다. 검색량·경쟁도·CPC는 미수집입니다.</p>
      {data.collection_sources.map(s => <article key={str(s, "id")}><h3>{str(s, "name")}</h3><p>{str(s, "endpoint")}</p><p>{str(s, "rights")} · <a href={str(s, "terms_url")} target="_blank" rel="noreferrer">이용 조건</a></p>
        <p>마지막 시도 {str(s, "last_attempt_at")} · 마지막 성공 {str(s, "last_successful_at") || str(s, "last_collected_at")} · 오류 {str(s, "last_error") || "없음"} · 이용 정책 {JSON.stringify(s.source_policy ?? {})}</p>
        <Editor disabled={busy} label="실제 자료 수집 실행" fields={[profileField, { name: "auto_generate", label: "검증된 모델만 후속 자동 초안 허용", type: "checkbox" }]}
          submit={body => act("collections", { ...body, source_id: s.id, idempotency_key: crypto.randomUUID() })}/>
        <Editor disabled={busy} label="수집 스케줄 저장" defaults={s} fields={[profileField, { name: "scheduled", label: "자동 수집", type: "checkbox" }, { name: "interval_minutes", label: "간격 분 (최소 60)", type: "number" }, { name: "auto_generate", label: "후속 자동 초안", type: "checkbox" }]}
          submit={body => act(`collections/${str(s, "id")}`, body, "PUT")}/>
      </article>)}
      <details><summary>조사 작업 진행·실패·재시도</summary><pre>{JSON.stringify(data.collection_jobs, null, 2)}</pre></details>
    </section>
    <section><h2>완성 원고 평가 (사람 검토 대기)</h2>
      {(data.article_evaluations ?? []).map(a => <article key={str(a, "id")}><h3>{str(a, "topic")} · {str(a, "language_code")} · {str(a, "status")}</h3>
        <p>주제 {str(a, "topic_key")} · 수집 출처 {JSON.stringify(a.source_ids ?? [])} · 사실 단위 {JSON.stringify(a.fact_ids ?? [])}</p>
        <p>모델 {str(a, "model")} · 처리 {str(a, "elapsed_ms")} ms · AI 호출 {str(a, "ai_calls")} · 사람 검토 필수 · 발행 준비 {String(a.publish_ready ?? false)}</p>
        <p>키워드 {JSON.stringify(a.keywords ?? [])}</p>
        {a.error_category ? <p>실패: {str(a, "error_category")}</p> : <><h4>{str(a, "saved_title") || str(a, "title")}</h4><p>{str(a, "summary")}</p><details><summary>전체 원고 미리보기</summary><pre>{str(a, "saved_body")}</pre></details></>}
        <details><summary>기계 검사와 자원 측정</summary><pre>{JSON.stringify({ checks: a.checks, metrics: a.metrics }, null, 2)}</pre></details>
      </article>)}
    </section>
    <ManuscriptManager articles={data.evaluation_results?.editorial_articles ?? []} blogs={data.prepublication?.blogs ?? []} categories={data.categories} busy={busy} publications={data.manuscript_publications ?? []} submit={act}/>
    <section aria-labelledby="phase4c-status">
      <h2 id="phase4c-status">Phase 4-C · SEC·Blogger·발행 안전 점검</h2>
      <p>SEC evaluation availability and source dependencies appear per language below. Historical SEC evaluations remain separate.</p>
      <h3>SEC per-language quota and prerequisite</h3>
      <table><thead><tr><th>Language</th><th>Quota</th><th>English source draft</th><th>Availability</th></tr></thead><tbody>
        {(data.evaluation_results?.sec_locale_availability ?? []).map(item => <tr key={str(item, "language_code")}><td>{str(item, "language_code")}</td><td>{str(item, "quota_used")}/{str(item, "quota_limit")} ? remaining {str(item, "quota_remaining")}</td><td>{item.source_draft_available === null ? "not required" : String(item.source_draft_available ?? false)}</td><td>{str(item, "status")}</td></tr>)}
      </tbody></table>
      <p>Localized SEC runs require a successful English source draft for the same source. English quota is separate; without that source draft, downstream locales remain blocked.</p>
      <details><summary>기존 SEC 품질 기록</summary><pre>{JSON.stringify(data.evaluation_results?.sec_historical_quality ?? [], null, 2)}</pre></details>
      <p>실제 Blogger 읽기 동기화: {data.prepublication?.real_blogger_sync_verified ? "검증됨" : "미검증"} · 연결된 Google 계정 {data.prepublication?.blogger_accounts_connected ?? 0}개</p>
      <p>0원 정책 차단 사유: {JSON.stringify((data.cost_policy?.blocked_providers as Row[] | undefined)?.filter(provider => provider.name === "google_blogger_read") ?? [])}. 외부 GET은 이 정책 차단을 우회하지 않습니다.</p>
      {(data.prepublication?.blogs ?? []).map(blog => {
        const prior = (data.prepublication?.historical_read_verifications as Row[] | undefined)?.find(event => event.blog_id === blog.id);
        const payload = (prior?.payload as Row | undefined) ?? {};
        return <article key={str(blog, "id")}><p>{str(blog, "language_code")} · {str(blog, "url")} · Blog ID {str(blog, "blog_id") || "미등록"} · OAuth {str(blog, "oauth_status") || "미연결"} · 마지막 조회 {str(blog, "last_checked_at") || "없음"} · 오류 {str(blog, "connection_error") || "없음"}</p>
          <p>과거 읽기 검증 기록 {str(prior ?? {}, "created_at") || "없음"} · 게시글 {prior ? str(payload, "posts") : "미검증"} · 페이지 {prior ? str(payload, "pages") : "미검증"} · 페이지 종료 {prior ? String(payload.terminal_page ?? false) : "미검증"}. 이번 Phase에서 실제 동기화는 수행하지 않았습니다.</p></article>;
      })}
      <details><summary>발행 차단 원본 데이터</summary><pre>{JSON.stringify({ ...(data.prepublication?.safety ?? {}), real_writes_enabled: data.prepublication?.real_writes_enabled, publish_ready: false }, null, 2)}</pre></details>
      <p>미검증: SEC 신규 추론, 실제 Blogger 인증 계정·4개 블로그 조회·게시글 상세/페이지네이션. 운영 발행은 비활성화 상태입니다.</p>
    </section>
    <section aria-labelledby="phase4i-adsense-readiness">
      <h2 id="phase4i-adsense-readiness">AdSense preparation checks (diagnostic only)</h2>
      <p>Captured {str((data.adsense_readiness ?? {}) as Row, "captured_at") || "not available"}. Approval prediction: not provided. Public Blogger checks stay unverified while the Blogger read-cost gate is closed. Drafts and internal publication records are not treated as public posts.</p>
      <p>Internal planning heuristics only: {str(data.adsense_readiness?.internal_recommendations ?? {}, "suggested_published_post_count")}; {str(data.adsense_readiness?.internal_recommendations ?? {}, "suggested_article_length")}. These are not Google requirements and are not approval gates.</p>
      {(data.adsense_readiness?.blogs ?? []).map(blog => <article key={str(blog, "blog_mapping_id")}>
        <h3>{str(blog, "language_code")} · {str(blog, "display_name")} · {str(blog, "url")}</h3>
        <p>Public posts: unverified · mapped Blogger ID: {str(blog, "blog_id") || "not registered"} · active: {String(blog.active ?? false)}</p>
        <table><thead><tr><th>Check</th><th>Status</th><th>Observed evidence / next step</th></tr></thead><tbody>
          {((blog.checks as Row[] | undefined) ?? []).map(item => <tr key={str(item, "key")}>
            <th scope="row">{str(item, "label")}</th><td>{str(item, "status")}</td>
            <td><details><summary>?? ??</summary><pre>{JSON.stringify(item.evidence, null, 2)}</pre></details></td>
          </tr>)}
        </tbody></table>
      </article>)}
      <p>Official references: {(data.adsense_readiness?.official_references ?? []).map((url, index) => <span key={url}>{index ? " · " : ""}<a href={url} target="_blank" rel="noreferrer">Google reference {index + 1}</a></span>)}</p>
    </section>
    <section aria-labelledby="phase4e-readiness">
      <h2 id="phase4e-readiness">Phase 4-E · 운영 준비 체크리스트</h2>
      <p>상태는 현재 operations DB, 격리 evaluation DB 스냅샷 및 명시된 과거 테스트 증거를 반영합니다. 사람 검토와 실제 발행 권한은 별도입니다.</p>
      <table><thead><tr><th>항목</th><th>상태</th><th>근거</th></tr></thead><tbody>
        {(data.operational_readiness?.items ?? []).map(item => <tr key={item.key}>
          <th scope="row">{item.key}</th><td>{item.status}</td><td><details><summary>근거 상세</summary><pre>{JSON.stringify(item.evidence, null, 2)}</pre></details></td>
        </tr>)}
      </tbody></table>
      <p>별도 운영 발행 승인: 미승인 · publish_ready=false · 실제 Blogger 쓰기 비활성화.</p>
    </section>
    <section><h2>키워드 후보·주제 선정</h2>
      <Editor disabled={busy} label="수동 후보 등록" defaults={{ priority: 50 }} fields={[profileField, categoryField, { name: "keyword", label: "키워드" }, { name: "search_intent", label: "검색 의도" }, { name: "collection_source", label: "수집 출처" }, { name: "rationale", label: "선정 근거" }, { name: "priority", label: "우선순위 1–100", type: "number" }, { name: "expires_at", label: "유효 기한", type: "datetime-local" }]} submit={body => act("keywords", body)}/>
      {data.keywords.map(k => <article key={str(k, "id")}><h3>{str(k, "keyword")} · {str(k, "language_code")} · {str(k, "status")}</h3>
        <p>{str(k, "collection_source")} · {str(k, "rationale")} · 검색량 {k.search_volume === null ? "미수집" : str(k, "search_volume")} · CPC {k.cpc === null ? "미수집" : str(k, "cpc")}</p>
        <button disabled={busy} onClick={() => act(`keywords/${str(k, "id")}`, { status: "selected" }, "PUT")}>선정</button>
        <button disabled={busy} onClick={() => act(`keywords/${str(k, "id")}`, { status: "excluded" }, "PUT")}>제외</button>
        <button disabled={busy || k.status !== "selected"} onClick={() => act("jobs", { keyword_id: k.id, idempotency_key: crypto.randomUUID() })}>설정된 Provider로 초안 생성</button>
        <button disabled={busy || k.status !== "selected" || !Boolean(data.controls.evaluation_isolated)} onClick={() => act("jobs", { keyword_id: k.id, evaluation_only: true, idempotency_key: crypto.randomUUID() })}>실제 AI 평가 초안 생성 (품질 보류)</button>
      </article>)}
    </section>
    <section><h2>수집 출처·검토 이력</h2><p>승인 정정은 새 검토를 추가합니다. 자동 출처 확인과 의미적 사실 검증을 구분하세요.</p>
      <Editor disabled={busy} label="출처 등록" fields={[{ name: "keyword_id", label: "키워드", options: data.keywords.map(k => ({ value: str(k, "id"), label: str(k, "keyword") })) }, { name: "url", label: "공개 HTTPS URL", type: "url" }, { name: "source_name", label: "출처명" }, { name: "source_language", label: "원문 언어 BCP 47 (미확인: und)" }, { name: "published_at", label: "게시일 (모르면 비움)", type: "datetime-local", optional: true }, { name: "evidence", label: "주요 근거 (최대 1,000자)", type: "textarea" }, { name: "reliability_reason", label: "신뢰성 근거" }, { name: "rights", label: "저작권·사용 범위" }, { name: "access_policy", label: "접근·robots 정책 확인" }, { name: "valid_until", label: "정보 유효 기한", type: "datetime-local" }, { name: "is_primary", label: "공식 1차 자료", type: "checkbox" }]} submit={body => act("sources", body)}/>
      {data.sources.map(s => <details key={str(s, "id")}><summary>{str(s, "source_name")} · 검토 {s.approved === true ? "승인 기록 있음" : "대기·불충분"} · {str(s, "valid_until")}</summary>
        <a href={str(s, "url")} target="_blank" rel="noreferrer">원문 출처</a><p>{str(s, "evidence")}</p><p>{str(s, "rights")} · {str(s, "reliability_reason")}</p><p>{str(s, "review_reason")}</p>
        <p>자료 언어: {str(s, "reviewed_source_language") || str(s, "source_language") || "und (미확인)"}</p>
        <Editor disabled={busy} label="새 검토 추가" defaults={{ source_language: str(s, "reviewed_source_language") || str(s, "source_language") || "und" }} fields={[{ name: "approved", label: "사실·권리 확인 (미선택은 거부 정정)", type: "checkbox" }, { name: "source_language", label: "검증된 원문 언어 (BCP 47 또는 und)" }, { name: "reason", label: "검토 근거 (10자 이상)" }, { name: "reviewer", label: "검토자" }]} submit={body => act(`sources/${str(s, "id")}/reviews`, body)}/>
        {s.approved === true && <button disabled={busy} onClick={() => act(`sources/${str(s, "id")}/facts`, {})}>승인 출처에서 사실 원장 추출</button>}
      </details>)}
    </section>
    <section><h2>근거 보존 다국어 현지화</h2>
      <p>검토 승인된 출처 구간만 사실 원장에 저장합니다. 용어집은 공식 번역 근거와 승인 기록이 있는 항목만 적용됩니다. 기계 검사 통과도 사람 검토를 대체하지 않으며 발행 준비는 항상 false입니다.</p>
      <p>사실 원장 {data.evidence_facts?.length ?? 0}건 · 현지화 평가 {data.localizations?.length ?? 0}건 · 용어집 변경 이력 {data.glossary_revisions?.length ?? 0}건</p>
      <label>대상 언어 <select value={targetLanguage} onChange={e => setTargetLanguage(e.target.value)}><option value="">언어 선택</option>{Array.from(new Set(data.profiles.map(p => str(p, "language_code")))).map(code => <option key={code} value={code}>{code}</option>)}</select></label>
      {(data.evidence_facts ?? []).map(f => <article key={str(f, "id")}><h3>{str(f, "source_language")} · 사실 {str(f, "fact_key")}</h3>
        <p>{str(f, "source_excerpt")}</p><p>보호된 숫자: {JSON.stringify(f.numeric_values ?? [])} · 보호된 날짜: {JSON.stringify(f.date_values ?? [])}</p>
        <p>출처 연결: {JSON.stringify(f.citation_ids)} · {str(f, "verification_status")}</p>
        <button disabled={busy || !targetLanguage} onClick={() => act("localizations", { fact_id: f.id, target_language: targetLanguage })}>이 근거 현지화</button>
      </article>)}
      {(data.localizations ?? []).map(item => { const output = item.output_snapshot as Row | undefined; const fact = data.evidence_facts?.find(f => f.id === item.fact_id); return <details key={str(item, "id")}><summary>{str(item, "target_language")} · {item.machine_passed ? "기계 검사 통과" : "품질 보류"} · 사람 검토 대기</summary>
        <p>원문: {str(fact ?? {}, "source_excerpt")}</p><p>현지화: {str(output ?? {}, "text")}</p><pre>{JSON.stringify({ metrics: item.metrics, checks: item.checks, source_ids: output?.source_ids, semantic_accuracy: output?.semantic_accuracy, naturalness: output?.naturalness, publish_ready: item.publish_ready }, null, 2)}</pre></details>; })}
      <details><summary>언어별 용어집 승인 상태</summary><pre>{JSON.stringify(data.glossary ?? [], null, 2)}</pre></details>
      <details><summary>용어집 append-only 변경 이력</summary><pre>{JSON.stringify(data.glossary_revisions ?? [], null, 2)}</pre></details>
    </section>
    <section><h2>생성 작업·취소·복구</h2><p>스트리밍 중지 시 해당 추론 연결을 닫습니다. 저장한 타깃은 보존하며 재개 시 중복 생성하지 않습니다.</p>
      <p>Evaluation isolation: {Boolean(data.controls.evaluation_isolated) ? "confirmed" : "not confirmed; evaluation runs are blocked"}; evaluation worker: {data.evaluation_worker?.status ? str(data.evaluation_worker, "status") : "not running"}.</p>
      {(data.daily_workload ?? []).map(q => <p key={str(q, "language_code")}>{str(q, "language_code")}: operations {str(q, "operations_used")}/{str(q, "operations_limit")}, evaluation {str(q, "evaluation_used")}/{str(q, "evaluation_limit")}; resets {str(q, "resets_at")}.</p>)}
      {data.jobs.map(j => <article key={str(j, "id")}><p>{str(j, "id")} · {str(j, "status")} · 시도 {str(j, "attempts")} · {str(j, "error_type")}</p>
        <button disabled={busy || j.status === "succeeded"} onClick={() => act(`jobs/${str(j, "id")}/action`, { action: j.paused ? "resume" : "pause" })}>{j.paused ? "재개" : "중지·현재 추론 취소"}</button>
        <button disabled={busy || j.status !== "failed" || Number(j.attempts) >= 3} onClick={() => act(`jobs/${str(j, "id")}/action`, { action: "retry" })}>재시도</button></article>)}
      <details><summary>실패·재시도 이력</summary><pre>{JSON.stringify(data.attempts, null, 2)}</pre></details>
    </section>
    <section><h2>Isolated evaluation results (read only)</h2>
      <p>Evaluation DB: {data.evaluation_results?.configured ? data.evaluation_results.available === false ? "unavailable" : str(data.evaluation_results as Row, "database") : "read-only connection not configured"}. Worker: {str(data.evaluation_results?.worker ?? {}, "status") || "not started"}; baseline snapshot {str(data.evaluation_results as Row, "baseline_snapshot_at")}. Human review remains pending; publish_ready is always false.</p>
      {data.evaluation_results?.error_category ? <p role="alert">{data.evaluation_results.error_category}</p> : null}
      {(data.evaluation_results?.quota ?? []).map(q => <p key={str(q, "language_code")}>Evaluation quota {str(q, "language_code")}: used {str(q, "quota_used")}/{str(q, "quota_limit")}; reserved {str(q, "reserved_slots")}; remaining after reservation {str(q, "remaining_after_reservation")}; resets {str(q, "resets_at")}.</p>)}
      <p>SEC English slot reservation: {String(data.evaluation_results?.sec_english_quota_reservation?.active ?? false)}; it is reserved within the daily cap, not added to it.</p>
      <h3>Fed·SEC 모델별 C3 비교 (실제 격리 평가 실행만)</h3>
      <p>같은 키워드·언어 그룹 안의 저장된 실행을 나란히 보여줍니다. 기계 검사 통과는 사람의 의미·자연스러움 검토나 발행 승인이 아닙니다.</p>
      {Object.entries(c3ModelComparisons).map(([key, group]) => <details key={key}>
        <summary>{group[0]?.sec_source ? "SEC" : "Federal Reserve"} · {str(group[0] ?? {}, "language_code")} · {group.length}개 실행</summary>
        <div style={{ overflowX: "auto" }}><table><thead><tr><th>모델</th><th>체크섬</th><th>실행 상태</th><th>초안 상태</th><th>경과 ms</th><th>기계 검사</th><th>측정</th></tr></thead><tbody>
          {group.map((run, index) => {
            const modelName = str(run, "model");
            const installed = ((local.installed_models as Row[] | undefined) ?? []).find(item => str(item, "name") === modelName);
            const metadata = (run.result_metadata as Row | undefined) ?? {};
            const quality = (metadata.quality as Row | undefined) ?? {};
            const grounding = (quality.grounding as Row | undefined) ?? {};
            const passed = run.run_status === "succeeded" && quality.structural_pass === true && grounding.rule_pass === true && quality.localization_pass !== false;
            return <tr key={`${str(run, "run_id")}-${index}`}><td>{modelName || "미기록"}</td><td>{str(installed ?? {}, "sha256") || "평가 산출물 참조"}</td><td>{str(run, "run_status")}</td><td>{str(run, "state") || "저장 초안 없음"}</td><td>{str(run, "elapsed_ms") || "미측정"}</td><td>{passed ? "통과" : "보류 또는 미측정"}</td><td><details><summary>?? ??</summary><pre>{JSON.stringify(quality.metrics ?? metadata.metrics ?? {}, null, 2)}</pre></details></td></tr>;
          })}
        </tbody></table></div>
      </details>)}
      {(data.evaluation_results?.runs ?? []).map((run, index) => <details key={`${str(run, "run_id")}-${index}`}>
        <summary>{str(run, "language_code")} | {str(run, "run_status")} | {str(run, "state")} | {str(run, "model")} | {str(run, "created_at")}</summary>
        <h3>{str(run, "title") || "No saved draft"}</h3>
        <pre style={{ whiteSpace: "pre-wrap" }}>{str(run, "body")}</pre>
        <p>저장된 실제 실행 결과</p><details><summary>실행 메타데이터·근거 JSON</summary><pre>{JSON.stringify({ error: run.error_type, attempts: run.attempts, elapsed_ms: run.elapsed_ms, result_metadata: run.result_metadata, evidence: run.source_snapshot, publish_ready: false }, null, 2)}</pre></details>
      </details>)}
      <details><summary>Stage audit data ({data.evaluation_results?.stages?.length ?? 0})</summary><pre>{JSON.stringify(data.evaluation_results?.stages ?? [], null, 2)}</pre></details>
      <details><summary>Evaluation audit events ({data.evaluation_results?.events?.length ?? 0})</summary><pre>{JSON.stringify(data.evaluation_results?.events ?? [], null, 2)}</pre></details>
    </section>
    <section><h2>단계별 생성 추적·근거 범위</h2>
      <p>진행과 완료 데이터는 PostgreSQL 실행 단계 기록에서 조회합니다. 검토된 출처 수는 활성 언어별·카테고리별 현재 승인 근거 집계이며 검색량이나 콘텐츠 품질 점수가 아닙니다.</p>
      <div style={{ overflowX: "auto" }}><table><thead><tr><th>카테고리</th><th>언어</th><th>승인된 근거 수</th></tr></thead><tbody>
        {data.coverage.map((item, index) => <tr key={index}><td>{str(item, "category")}</td><td>{str(item, "language_code")}</td><td>{str(item, "reviewed_source_count")}</td></tr>)}
      </tbody></table></div>
      {data.stage_runs.map(stage => <details key={str(stage, "id")}><summary>{str(stage, "stage_name")} · {str(stage, "status")} · {str(stage, "profile_id")} · {str(stage, "started_at")} · {str(stage, "error_category")}</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify({ execution_id: stage.id, run_id: stage.run_id, worker_attempt: stage.worker_attempt, stage_attempt: stage.stage_attempt, sequence: stage.sequence, model: stage.model, prompt_version: stage.prompt_version, elapsed_ms: stage.elapsed_ms, source_ids: stage.source_ids, input: stage.input_snapshot, output: stage.output_snapshot, validation: stage.validation }, null, 2)}</pre></details>)}
    </section>
    <section><h2>원본·언어별 초안·품질·버전 비교</h2><p>quality_held는 품질 미달·미확인 보존본입니다. 내부 점수는 순위·수익 보장이 아니며 모든 발행 준비 상태는 false입니다.</p>
      {[{ id: left, set: setLeft }, { id: right, set: setRight }].map((item, index) => <label key={index}>비교 {index + 1}<select value={item.id} onChange={e => item.set(e.target.value)}><option value="">초안 선택</option>{data.versions.map(v => <option key={str(v, "id")} value={str(v, "id")}>{str(v, "language")} v{str(v, "version")} · {str(v, "state")} · {str(v, "title")}</option>)}</select></label>)}
      {versions[0] && versions[1] && <p>추가 행 {str(versions[1], "body").split("\n").filter(line => !str(versions[0]!, "body").split("\n").includes(line)).length} · 삭제 행 {str(versions[0], "body").split("\n").filter(line => !str(versions[1]!, "body").split("\n").includes(line)).length}</p>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 20 }}>{versions.map((v, index) => v && <article key={index}><h3>{str(v, "title")}</h3><p>{str(v, "language")} · {str(v, "state")} · {str(v, "model")} · 원본 {str(v, "source_version_id") || "본 버전"}</p><details><summary>원고 본문 미리보기</summary><pre style={{ whiteSpace: "pre-wrap" }}>{str(v, "body")}</pre></details><button disabled={busy} onClick={() => act(`versions/${str(v, "id")}/validate`, {})}>품질 검사 다시 실행</button><details><summary>메타 설명·규칙/모델 검증·처리 시간·CPU/RAM</summary><pre>{JSON.stringify({ generation: v.result_metadata, latest_checks: v.latest_checks, references: v.source_snapshot }, null, 2)}</pre></details></article>)}</div>
    </section>
    <section><h2>언어별 모델·프롬프트 정책</h2><p>시험 생성은 품질 평가 완료를 선언하지 않습니다. 언어 지원 검증이 안 된 모델은 정상 자동 처리하지 않습니다. llama.cpp 모델·스레드 변경은 전용 엔진 재시작이 필요합니다.</p>
      {data.settings.map(s => <article key={str(s, "profile_id")}><h3>{profileLabel(data.profiles.find(p => p.id === s.profile_id) ?? {})}</h3>
        <Editor disabled={busy} label="언어 실행 정책 저장" defaults={s} fields={[{ name: "provider", label: "Provider", options: [{ value: "mock", label: "Mock 합성 테스트" }, { value: "local", label: "실제 Local" }] }, { name: "engine", label: "로컬 엔진", options: [{ value: "ollama", label: "Ollama 11434" }, { value: "llamacpp", label: "프로젝트 llama.cpp 11435" }] }, { name: "model", label: "설치 모델 이름" }, { name: "prompt_id", label: "프롬프트 버전", options: promptOptions }, { name: "enabled", label: "처리 허용", type: "checkbox" }, { name: "language_verified", label: "언어별 품질 평가 완료 (검증 근거 필수)", type: "checkbox" }, { name: "verification_reason", label: "언어 평가 근거", optional: true }, { name: "daily_limit", label: "일일 작업 한도", type: "number" }, { name: "evaluation_daily_limit", label: "Operations DB evaluation limit (isolated evaluation quota is displayed above)", type: "number" }, { name: "threads", label: "CPU 스레드 1–4", type: "number" }, { name: "timeout_seconds", label: "타임아웃 5–180초", type: "number" }]} submit={body => act(`settings/${str(s, "profile_id")}`, body, "PUT")}/>
      </article>)}
      <Editor disabled={busy} label="새 프롬프트 버전 추가" fields={[{ name: "name", label: "영문 이름" }, { name: "instructions", label: "새 지시문", type: "textarea" }]} submit={body => act("prompts", body)}/>
    </section>
    <section id="automation"><h2>자원·초안 스케줄</h2>
      <Editor disabled={busy} label="자원 정책 저장" defaults={data.controls} fields={[{ name: "paused", label: "전체 중지", type: "checkbox" }, { name: "max_concurrency", label: "동시 작업 1–2", type: "number" }, { name: "cpu_percent", label: "실행 전 CPU 한도 %", type: "number" }, { name: "ram_percent", label: "실행 전 RAM 한도 %", type: "number" }]} submit={body => act("controls", body, "PUT")}/>
      <Editor disabled={busy} label="카테고리 초안 스케줄 저장" defaults={{ schedule_cron: "0 9 * * *", timezone: "Asia/Seoul", quantity: 1 }} fields={[categoryField, profileField, { name: "active", label: "활성화", type: "checkbox" }, { name: "schedule_cron", label: "Cron (최소 5분)" }, { name: "timezone", label: "시간대" }, { name: "quantity", label: "회당 수량", type: "number" }]} submit={body => act("schedules", body)}/>
      <details><summary>등록 스케줄·전달 상태</summary><pre>{JSON.stringify({ schedules: data.schedules, dispatches: data.dispatches }, null, 2)}</pre></details>
    </section>
    <details><summary>최근 감사 기록</summary><pre>{JSON.stringify(data.events, null, 2)}</pre></details>
  </>;
}
