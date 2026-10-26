"use client";
import { useEffect, useState, type FormEvent } from "react";

type Row = Record<string, unknown>;
export type State = {
  profiles: Row[]; categories: Row[]; keywords: Row[]; sources: Row[]; jobs: Row[];
  versions: Row[]; settings: Row[]; prompts: Row[]; controls: Row; schedules: Row[];
  attempts: Row[]; events: Row[]; dispatches: Row[]; collection_sources: Row[]; cost_policy?: Row;
  collection_jobs: Row[]; measurements: Row[]; stage_runs: Row[]; coverage: Row[]; experiments?: Row[];
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
  async function refresh() {
    const [state, ai] = await Promise.all([fetch("/api/research/state", { cache: "no-store" }), fetch("/api/research/local-ai", { cache: "no-store" })]);
    if (!state.ok || !ai.ok) throw new Error("상태 조회 실패");
    setData(await state.json() as State); setLocal(await ai.json() as Row);
  }
  useEffect(() => { const timer = setInterval(() => { refresh().catch(() => setMessage("상태 갱신 실패")); }, 5000); return () => clearInterval(timer); }, []);
  async function act(path: string, body: Row, method = "POST") {
    setBusy(true);
    try {
      const response = await fetch(`/api/research/${path}`, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const value = await response.json() as Row;
      if (!response.ok) throw new Error(String(value.error ?? JSON.stringify(value.detail ?? "요청 실패")));
      setMessage("저장했습니다. 대기 작업은 Worker가 처리합니다."); await refresh();
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
    <section><h2>근거 우선 A/B 평가</h2>
      <p>저장된 Phase 3.7 원고 재평가와 사실 고정 템플릿 실험입니다. 규칙 검사 결과와 사람 검토 대기를 구분하며, 발행 준비는 항상 false입니다.</p>
      <p>최신 비교 평가 품질 보류: {currentExperiments.filter(e => !e.mechanical_gate_passed).length}건 · 사람 검토 대기: {currentExperiments.filter(e => e.human_review_required).length}건 · 근거 연결 실패: {unlinkedEvidenceCount}건</p>
      <p>실패 사유별 건수: {Object.entries(experimentFailureCounts).map(([name, count]) => `${name} ${count}`).join(" · ") || "없음"}</p>
      {experiments.map(e => <details key={str(e, "id")}><summary>{str(e, "language")} · {str(e, "variant")} · {e.mechanical_gate_passed ? "규칙 게이트 통과" : "품질 보류"} · {str(e, "created_at")}</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify({ experiment_id: e.experiment_id, source_version: e.content_version_id, processing: e.metrics, checks: e.checks, publish_ready: e.publish_ready, output: e.output_snapshot }, null, 2)}</pre></details>)}
    </section>
    <section><h2>Zero additional cost policy</h2><p>External gate: {data.cost_policy?.external_calls_allowed ? "active; check provider-specific blocks" : "blocked by credential or terms review"}</p><p>Paid fallback and automatic paid upgrades are disabled.</p><pre>{JSON.stringify({ blockedProviders: data.cost_policy?.blocked_providers ?? [], credentialNames: data.cost_policy?.blocked_credential_names ?? [] }, null, 2)}</pre></section>
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
      <p>Fed 공식 본문과 Wikidata CC0 구조화 메타데이터만 허용합니다. Wikidata 후보는 공식 발표·시세·영업·효능 검증 자료가 아니며 승인 대기입니다. 검색량·경쟁도·CPC는 미수집입니다.</p>
      {data.collection_sources.map(s => <article key={str(s, "id")}><h3>{str(s, "name")}</h3><p>{str(s, "endpoint")}</p><p>{str(s, "rights")} · <a href={str(s, "terms_url")} target="_blank" rel="noreferrer">이용 조건</a></p>
        <p>마지막 수집 {str(s, "last_collected_at")} · 오류 {str(s, "last_error") || "없음"} · 시간당 최대 한 번</p>
        <Editor disabled={busy} label="실제 자료 수집 실행" fields={[profileField, { name: "auto_generate", label: "검증된 모델만 후속 자동 초안 허용", type: "checkbox" }]}
          submit={body => act("collections", { ...body, source_id: s.id, idempotency_key: crypto.randomUUID() })}/>
        <Editor disabled={busy} label="수집 스케줄 저장" defaults={s} fields={[profileField, { name: "scheduled", label: "자동 수집", type: "checkbox" }, { name: "interval_minutes", label: "간격 분 (최소 60)", type: "number" }, { name: "auto_generate", label: "후속 자동 초안", type: "checkbox" }]}
          submit={body => act(`collections/${str(s, "id")}`, body, "PUT")}/>
      </article>)}
      <details><summary>조사 작업 진행·실패·재시도</summary><pre>{JSON.stringify(data.collection_jobs, null, 2)}</pre></details>
    </section>
    <section><h2>키워드 후보·주제 선정</h2>
      <Editor disabled={busy} label="수동 후보 등록" defaults={{ priority: 50 }} fields={[profileField, categoryField, { name: "keyword", label: "키워드" }, { name: "search_intent", label: "검색 의도" }, { name: "collection_source", label: "수집 출처" }, { name: "rationale", label: "선정 근거" }, { name: "priority", label: "우선순위 1–100", type: "number" }, { name: "expires_at", label: "유효 기한", type: "datetime-local" }]} submit={body => act("keywords", body)}/>
      {data.keywords.map(k => <article key={str(k, "id")}><h3>{str(k, "keyword")} · {str(k, "language_code")} · {str(k, "status")}</h3>
        <p>{str(k, "collection_source")} · {str(k, "rationale")} · 검색량 {k.search_volume === null ? "미수집" : str(k, "search_volume")} · CPC {k.cpc === null ? "미수집" : str(k, "cpc")}</p>
        <button disabled={busy} onClick={() => act(`keywords/${str(k, "id")}`, { status: "selected" }, "PUT")}>선정</button>
        <button disabled={busy} onClick={() => act(`keywords/${str(k, "id")}`, { status: "excluded" }, "PUT")}>제외</button>
        <button disabled={busy || k.status !== "selected"} onClick={() => act("jobs", { keyword_id: k.id, idempotency_key: crypto.randomUUID() })}>설정된 Provider로 초안 생성</button>
        <button disabled={busy || k.status !== "selected"} onClick={() => act("jobs", { keyword_id: k.id, evaluation_only: true, idempotency_key: crypto.randomUUID() })}>실제 AI 평가 초안 생성 (품질 보류)</button>
      </article>)}
    </section>
    <section><h2>수집 출처·검토 이력</h2><p>승인 정정은 새 검토를 추가합니다. 자동 출처 확인과 의미적 사실 검증을 구분하세요.</p>
      <Editor disabled={busy} label="출처 등록" fields={[{ name: "keyword_id", label: "키워드", options: data.keywords.map(k => ({ value: str(k, "id"), label: str(k, "keyword") })) }, { name: "url", label: "공개 HTTPS URL", type: "url" }, { name: "source_name", label: "출처명" }, { name: "published_at", label: "게시일 (모르면 비움)", type: "datetime-local", optional: true }, { name: "evidence", label: "주요 근거 (최대 1,000자)", type: "textarea" }, { name: "reliability_reason", label: "신뢰성 근거" }, { name: "rights", label: "저작권·사용 범위" }, { name: "access_policy", label: "접근·robots 정책 확인" }, { name: "valid_until", label: "정보 유효 기한", type: "datetime-local" }, { name: "is_primary", label: "공식 1차 자료", type: "checkbox" }]} submit={body => act("sources", body)}/>
      {data.sources.map(s => <details key={str(s, "id")}><summary>{str(s, "source_name")} · 검토 {s.approved === true ? "승인 기록 있음" : "대기·불충분"} · {str(s, "valid_until")}</summary>
        <a href={str(s, "url")} target="_blank" rel="noreferrer">원문 출처</a><p>{str(s, "evidence")}</p><p>{str(s, "rights")} · {str(s, "reliability_reason")}</p><p>{str(s, "review_reason")}</p>
        <Editor disabled={busy} label="새 검토 추가" fields={[{ name: "approved", label: "사실·권리 확인 (미선택은 거부 정정)", type: "checkbox" }, { name: "reason", label: "검토 근거 (10자 이상)" }, { name: "reviewer", label: "검토자" }]} submit={body => act(`sources/${str(s, "id")}/reviews`, body)}/>
      </details>)}
    </section>
    <section><h2>생성 작업·취소·복구</h2><p>스트리밍 중지 시 해당 추론 연결을 닫습니다. 저장한 타깃은 보존하며 재개 시 중복 생성하지 않습니다.</p>
      {data.jobs.map(j => <article key={str(j, "id")}><p>{str(j, "id")} · {str(j, "status")} · 시도 {str(j, "attempts")} · {str(j, "error_type")}</p>
        <button disabled={busy || j.status === "succeeded"} onClick={() => act(`jobs/${str(j, "id")}/action`, { action: j.paused ? "resume" : "pause" })}>{j.paused ? "재개" : "중지·현재 추론 취소"}</button>
        <button disabled={busy || j.status !== "failed" || Number(j.attempts) >= 3} onClick={() => act(`jobs/${str(j, "id")}/action`, { action: "retry" })}>재시도</button></article>)}
      <details><summary>실패·재시도 이력</summary><pre>{JSON.stringify(data.attempts, null, 2)}</pre></details>
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
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 20 }}>{versions.map((v, index) => v && <article key={index}><h3>{str(v, "title")}</h3><p>{str(v, "language")} · {str(v, "state")} · {str(v, "model")} · 원본 {str(v, "source_version_id") || "본 버전"}</p><pre style={{ whiteSpace: "pre-wrap" }}>{str(v, "body")}</pre><button disabled={busy} onClick={() => act(`versions/${str(v, "id")}/validate`, {})}>품질 검사 다시 실행</button><details open><summary>메타 설명·규칙/모델 검증·처리 시간·CPU/RAM</summary><pre>{JSON.stringify({ generation: v.result_metadata, latest_checks: v.latest_checks, references: v.source_snapshot }, null, 2)}</pre></details></article>)}</div>
    </section>
    <section><h2>언어별 모델·프롬프트 정책</h2><p>시험 생성은 품질 평가 완료를 선언하지 않습니다. 언어 지원 검증이 안 된 모델은 정상 자동 처리하지 않습니다. llama.cpp 모델·스레드 변경은 전용 엔진 재시작이 필요합니다.</p>
      {data.settings.map(s => <article key={str(s, "profile_id")}><h3>{profileLabel(data.profiles.find(p => p.id === s.profile_id) ?? {})}</h3>
        <Editor disabled={busy} label="언어 실행 정책 저장" defaults={s} fields={[{ name: "provider", label: "Provider", options: [{ value: "mock", label: "Mock 합성 테스트" }, { value: "local", label: "실제 Local" }] }, { name: "engine", label: "로컬 엔진", options: [{ value: "ollama", label: "Ollama 11434" }, { value: "llamacpp", label: "프로젝트 llama.cpp 11435" }] }, { name: "model", label: "설치 모델 이름" }, { name: "prompt_id", label: "프롬프트 버전", options: promptOptions }, { name: "enabled", label: "처리 허용", type: "checkbox" }, { name: "language_verified", label: "언어별 품질 평가 완료 (검증 근거 필수)", type: "checkbox" }, { name: "verification_reason", label: "언어 평가 근거", optional: true }, { name: "daily_limit", label: "일일 작업 한도", type: "number" }, { name: "threads", label: "CPU 스레드 1–4", type: "number" }, { name: "timeout_seconds", label: "타임아웃 5–180초", type: "number" }]} submit={body => act(`settings/${str(s, "profile_id")}`, body, "PUT")}/>
      </article>)}
      <Editor disabled={busy} label="새 프롬프트 버전 추가" fields={[{ name: "name", label: "영문 이름" }, { name: "instructions", label: "새 지시문", type: "textarea" }]} submit={body => act("prompts", body)}/>
    </section>
    <section><h2>자원·초안 스케줄</h2>
      <Editor disabled={busy} label="자원 정책 저장" defaults={data.controls} fields={[{ name: "paused", label: "전체 중지", type: "checkbox" }, { name: "max_concurrency", label: "동시 작업 1–2", type: "number" }, { name: "cpu_percent", label: "실행 전 CPU 한도 %", type: "number" }, { name: "ram_percent", label: "실행 전 RAM 한도 %", type: "number" }]} submit={body => act("controls", body, "PUT")}/>
      <Editor disabled={busy} label="카테고리 초안 스케줄 저장" defaults={{ schedule_cron: "0 9 * * *", timezone: "Asia/Seoul", quantity: 1 }} fields={[categoryField, profileField, { name: "active", label: "활성화", type: "checkbox" }, { name: "schedule_cron", label: "Cron (최소 5분)" }, { name: "timezone", label: "시간대" }, { name: "quantity", label: "회당 수량", type: "number" }]} submit={body => act("schedules", body)}/>
      <details><summary>등록 스케줄·전달 상태</summary><pre>{JSON.stringify({ schedules: data.schedules, dispatches: data.dispatches }, null, 2)}</pre></details>
    </section>
    <details><summary>최근 감사 기록</summary><pre>{JSON.stringify(data.events, null, 2)}</pre></details>
  </>;
}
