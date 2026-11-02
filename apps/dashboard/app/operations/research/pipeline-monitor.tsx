"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./pipeline-monitor.module.css";

type Run = { id: string; stage: string; scope_key: string; engine_version: string; settings_id: number; status: string; checkpoint: string; owner_pid: number; attempt: number; processed: number; remaining: number | null; last_progress_at: string; elapsed_ms: number | null; stalled_suspected: boolean; error_category: string | null; result: { regions?: number; successes?: number; failures?: number } };
type Pipeline = { health: string; settings: { collection_enabled: boolean; authoring_enabled: boolean }; last_attempt: string | null; last_success: string | null; interval_minutes: number; regions: number; collection_delayed: boolean; runs: Run[]; means: { stage: string; mean_ms: number }[]; authoring: { state: string; n: number; progress_at: string | null }[]; imports: { n: number; latest: string | null }; quality: { stage: string; status: string; n: number }[]; usage_signal: { active: boolean; error_code: string; not_before: string } | null };
const names: Record<string, string> = { trends_collection: "Trends 수집", topic_evaluation: "주제 평가", research_import: "원고 Import", queued: "작성 대기", researching: "웹 조사 중", writing: "작성 중", validating: "원고 검증 중", import_pending: "작성 완료 · Import 대기", imported_review: "Import 완료 · 검토 필요", failed: "실패", cancelled: "취소", running: "진행 중", completed: "완료", partial: "부분 성공", paused: "안전 보류", superseded: "최신 회차로 대체", collecting_normally: "수집 이력 정상 범위", collection_delayed: "데이터 수집 정체 의심", worker_unavailable: "Worker 상태 확인 필요", disabled: "수집 설정 OFF" };
const label = (value: string) => names[value] ?? value;
const stamp = (value: string | null) => value ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "기록 없음";

export default function PipelineMonitor() {
  const [data, setData] = useState<Pipeline | null>(null);
  const [error, setError] = useState("");
  const [stage, setStage] = useState(""); const [status, setStatus] = useState(""); const [query, setQuery] = useState("");
  const inFlight = useRef(false);
  const load = useCallback(async () => {
    if (inFlight.current) return; inFlight.current = true;
    try {
      const response = await fetch("/api/research/editorial-intelligence/pipeline", { cache: "no-store", signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new Error("단계별 상태 조회 실패");
      setData(await response.json() as Pipeline); setError("");
    } catch { setError("파이프라인 상태를 확인할 수 없습니다. 마지막 조회 결과는 현재 정상 동작의 증거가 아닙니다."); }
    finally { inFlight.current = false; }
  }, []);
  useEffect(() => { void Promise.resolve().then(load); const timer = setInterval(() => void load(), 10000); return () => clearInterval(timer); }, [load]);
  const runs = data?.runs.filter(r => (!stage || r.stage === stage) && (!status || r.status === status) && `${r.id} ${r.scope_key} ${r.checkpoint}`.toLowerCase().includes(query.toLowerCase())) ?? [];
  const collection = data?.runs.find(r => r.stage === "trends_collection");
  return <section className={styles.root} aria-label="연구 파이프라인 모니터">
    <div><h2>단계별 파이프라인</h2><p>수집·평가·작성·Import는 독립적으로 진행합니다. heartbeat와 실제 처리 진전을 구분합니다.</p></div>
    {error && <p role="alert" className={styles.warning}>{error}</p>}
    {!data ? <p role="status">{error ? "상태 확인 대기" : "단계별 상태 조회 중"}</p> : <>
      <p role="status" className={data.collection_delayed ? styles.warning : styles.state}>{label(data.health)} · 수집 {data.settings.collection_enabled ? "ON" : "OFF"} · 자동 작성 {data.settings.authoring_enabled ? "ON" : "OFF"}</p>
      {data.runs.some(r => r.stalled_suspected) && <p className={styles.warning}>마지막 진행이 지연된 단계가 있습니다. 다른 단계의 정상 여부와 별도로 확인해야 하며, 이 화면은 프로세스를 강제 종료하지 않습니다.</p>}
      <div className={styles.grid}>
        <article><h3>Google Trends 수집</h3><p>{data.interval_minutes}분 주기 · {data.regions}개 지역</p><p>최근 시도 {stamp(data.last_attempt)}</p><p>최근 성공 {stamp(data.last_success)}</p>{collection ? <><p>최근 회차: {collection.scope_key}</p><p>{label(collection.status)} · 성공 {collection.result.successes ?? "미확인"} / 시도 {collection.result.regions ?? "미확인"}</p></> : <p>단계별 수집 회차 기록 없음</p>}<p>누락 회차는 감사에 기록하며 일괄 재실행하지 않습니다.</p></article>
        <article><h3>주제 평가</h3>{data.runs.find(r => r.stage === "topic_evaluation") ? <p>{label(data.runs.find(r => r.stage === "topic_evaluation")!.status)}</p> : <p>평가 실행 기록 없음 · 수집 완료 대기</p>}<p>동일 후보·평가 설정·엔진의 결과를 재사용합니다.</p>{data.means.filter(m => m.stage === "topic_evaluation").map(m => <p key={m.stage}>측정된 평균 처리 시간 {(m.mean_ms / 1000).toFixed(2)}초</p>)}</article>
        <article><h3>Codex 작성 및 Import</h3>{data.authoring.length ? data.authoring.map(r => <p key={r.state}>{label(r.state)}: {r.n}건</p>) : <p>작성 Job 없음</p>}{data.usage_signal?.active && <p className={styles.warning}>Codex 사용량/가용성 대기 · {data.usage_signal.error_code}<br />로컬 재시도 가능 시각 {stamp(data.usage_signal.not_before)} · 제공자 초기화 시각은 미확인</p>}<p>전체 Import 이력 {data.imports.n}건 · 최근 {stamp(data.imports.latest)}</p><p>Import 완료는 사실 검증·발행 승인이 아닙니다.</p></article>
        <article><h3>품질 평가</h3>{data.quality.length ? data.quality.map(r => <p key={`${r.stage}-${r.status}`}>{r.stage === "static" ? "정적 평가" : "Codex 심층 평가"} · {label(r.status)}: {r.n}건</p>) : <p>평가 기록 없음</p>}<p>수정 제안은 사용자 승인 후 새 Content Version으로 적용합니다.</p></article>
      </div>
      <div className={styles.filters}><label>단계<select value={stage} onChange={e => setStage(e.target.value)}><option value="">전체 단계</option>{["trends_collection", "topic_evaluation", "research_import"].map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label><label>처리 상태<select value={status} onChange={e => setStatus(e.target.value)}><option value="">전체 상태</option>{["running", "completed", "partial", "failed", "paused", "superseded"].map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label><label>회차·Job 검색<input value={query} onChange={e => setQuery(e.target.value)} maxLength={150} /></label></div>
      <p>최근 단계 실행 100건 · 원고 작성 상태는 기존 Codex Job에서 조회합니다.</p>
      {runs.length ? <div className={styles.runs}>{runs.map(r => <article key={r.id}><h3>{label(r.stage)} · {r.stalled_suspected ? "진행 지연 의심" : label(r.status)}</h3><p>Job {r.id}</p><p>회차 {r.scope_key}</p><p>마지막 진행 {stamp(r.last_progress_at)} · PID {r.owner_pid}</p><p>체크포인트 {r.checkpoint} · 처리 {r.processed} · 남음 {r.remaining ?? "확인 불가"}</p><p>시도 {r.attempt} · 소요 {r.elapsed_ms === null ? "진행 중" : `${(r.elapsed_ms / 1000).toFixed(2)}초`} · 엔진 {r.engine_version} · 평가 설정 {r.settings_id || "해당 없음"}</p>{r.error_category && <p className={styles.warning}>오류: {r.error_category}</p>}</article>)}</div> : <p>조건에 맞는 단계 실행 기록이 없습니다.</p>}
    </>}
  </section>;
}
