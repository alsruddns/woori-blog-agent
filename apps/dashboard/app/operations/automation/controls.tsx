"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./controls.module.css";

type MainKey = "trends_collection_enabled" | "auto_manuscript_enabled" | "auto_publishing_enabled" | "manual_publishing_enabled";
type Key = MainKey | "trends_auto_publishing_enabled" | "scheduled_auto_publishing_enabled" | "automatic_publication_operator_approved";
type Settings = Record<Key, boolean> & { revision: number; emergency_stop: boolean; blogger_api_restricted: boolean; configured_mode: string; operations_auto_approved: boolean; blogger_write_mode: string; interval_minutes: number; trends_authoring_min_volume: number; global_publish_min_interval_minutes: number; global_daily_live_publish_limit: number; auto_mode: "draft" | "publish"; auto_blog_ids: string[]; google_account_report: string; automatic_publication_approval_actor: string | null; automatic_publication_approval_reason: string | null; automatic_publication_approval_changed_at: string | null; read_check_result: { checked_at?: string; results?: { blog_id: string; read_available: boolean; reason?: string }[] } };
type Change = { key: Key | "emergency_stop" | "google_account_available"; value: boolean; revision?: number } | { key: "global_publish_min_interval_minutes" | "trends_authoring_min_volume"; value: number; revision?: number } | { key: "auto_policy"; revision?: number };
type Snapshot = { settings: Settings & { updated_at?: string }; automatic_publication_approval: { approved: boolean; effective: boolean; worker_applied: boolean; blockers: string[]; pending_auto_jobs: number; legacy_operations_auto_approved: boolean; configured_mode: string; blogger_write_mode: string; external_cost_policy_approved: boolean; external_public_write_approved: boolean; scope: Record<string, unknown>; actor: string | null; reason: string | null; changed_at: string | null }; effective: Record<Key, string>; workers: { service_name: string; process_id: number; policy_applied: boolean; applied_revision?: number; engine_version?: string; policy_seen_at?: string }[]; history: { id: number; created_at: string; payload: { actor: string; reason: string; changes: { key: string; before: unknown; after: unknown }[] } }[]; blogs: { id: string; display_name: string; language_code: string }[]; recent: { last_collection: string | null; last_import: string | null; last_authoring: string | null; authoring_queued: number; authoring_running: number; region_count: number }; eligible_jobs: number; last_publication: { remote_status: string; remote_verified_at: string } | null };
const title: Record<MainKey, string> = { trends_collection_enabled: "Google Trends 수집", auto_manuscript_enabled: "Codex 자동 원고 작성", auto_publishing_enabled: "Blogger 자동 발행", manual_publishing_enabled: "Blogger 수동 발행" };
const originTitle = { trends_auto_publishing_enabled: "Google Trends 원고 자동 발행", scheduled_auto_publishing_enabled: "일일 예약 원고 자동 발행" } as const;
const originKey = (key: Change["key"]): key is keyof typeof originTitle => key in originTitle;
const stamp = (value: string | null | undefined) => value ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "기록 없음";

export default function Controls() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [actor, setActor] = useState("관리자");
  const [reason, setReason] = useState("운영 목적을 위해 설정을 변경함");
  const [intervalDraft, setIntervalDraft] = useState("15");
  const [volumeDraft, setVolumeDraft] = useState("5000");
  const [mode, setMode] = useState<"draft" | "publish">("draft");
  const [blogs, setBlogs] = useState<string[]>([]);
  const [pending, setPending] = useState<Change | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [liveConfirmed, setLiveConfirmed] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const awaiting = useRef<number | null>(null);
  const awaitingServices = useRef<string[]>(["research_worker", "publication_worker"]);
  const initialized = useRef(false);
  const policyDirty = useRef(false);
  const lastRevision = useRef(0);
  const intervalDirty = useRef(false);
  const volumeDirty = useRef(false);
  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/automation-controls", { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? result.detail ?? "운영 설정을 조회할 수 없습니다.");
      const snapshot = result as Snapshot;
      if (snapshot.settings.revision < lastRevision.current) return;
      lastRevision.current = snapshot.settings.revision;
      if (!initialized.current || !policyDirty.current) { setMode(snapshot.settings.auto_mode); setBlogs(snapshot.settings.auto_blog_ids); initialized.current = true; }
      if (!intervalDirty.current) setIntervalDraft(String(snapshot.settings.global_publish_min_interval_minutes));
      if (!volumeDirty.current) setVolumeDraft(String(snapshot.settings.trends_authoring_min_volume ?? 5000));
      setData(current => !current || snapshot.settings.revision >= current.settings.revision ? snapshot : current); setError("");
      if (awaiting.current !== null && snapshot.settings.revision >= awaiting.current && awaitingServices.current.every(service => snapshot.workers.some(w => w.service_name === service && w.policy_applied && w.applied_revision === awaiting.current))) { setToast(snapshot.settings.emergency_stop ? "Worker ?? ?? ? ?? ??? ?? ??" : "Worker ?? ??"); awaiting.current = null; }
    } catch (err) { setError(err instanceof Error ? err.message : "조회 실패"); }
  }, []);
  useEffect(() => { void Promise.resolve().then(load); const timer = setInterval(() => void load(), 5000); return () => clearInterval(timer); }, [load]);
  useEffect(() => { if (pending) dialog.current?.showModal(); else dialog.current?.close(); }, [pending]);
  async function save(change: Change, confirmation = false) {
    if (!data) return;
    if (actor.trim().length < 2 || reason.trim().length < 10) { setFormError("변경자는 2자 이상, 변경 사유는 10자 이상 입력하세요."); return; }
    if (busy) return;
    setFormError(""); setSaveError("");
    setBusy(true);
    try {
      const auto = change.key === "auto_publishing_enabled" && change.value;
      const policy = change.key === "auto_policy";
      const response = await fetch("/api/automation-controls", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: change.revision ?? data.settings.revision, actor: actor.trim(), reason: reason.trim(), ...(change.key === "auto_policy" ? { auto_mode: mode, auto_blog_ids: blogs } : { [change.key]: change.value }), ...(change.key !== "auto_policy" && originKey(change.key) && change.value ? { confirm_auto: confirmation, confirm_live: liveConfirmed } : {}), ...(auto ? { auto_mode: mode, auto_blog_ids: blogs, confirm_auto: confirmation, confirm_live: liveConfirmed } : {}), ...(policy ? { confirm_auto: confirmation, confirm_live: liveConfirmed } : {}), confirm_emergency_release: change.key === "emergency_stop" && !change.value && confirmation, confirm_operator_auto_approval: change.key === "automatic_publication_operator_approved" && confirmation }) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : result.error ?? "설정 변경에 실패했습니다.");
      lastRevision.current = result.revision; awaiting.current = result.revision; awaitingServices.current = change.key === "automatic_publication_operator_approved" ? ["publication_worker"] : ["research_worker", "publication_worker"]; policyDirty.current = false; intervalDirty.current = false; volumeDirty.current = false; setToast("설정 저장 완료 · Worker 적용 대기"); setPending(null); window.dispatchEvent(new Event("woori-automation-policy-changed")); await load();
    } catch (err) { const message = `설정 변경 실패: ${err instanceof Error ? err.message : "다시 시도하세요."}`; setSaveError(message); setToast(message); if (err instanceof Error && err.message.includes("최신 상태")) { policyDirty.current = false; setPending(null); await load(); } } finally { setBusy(false); }
  }
  function toggle(change: Change) {
    if (busy || !data) return;
    if (actor.trim().length < 2 || reason.trim().length < 10) { setFormError("변경자는 2자 이상, 변경 사유는 10자 이상 입력하세요."); return; }
    setFormError(""); setSaveError("");
    const next = { ...change, revision: data.settings.revision };
    if (change.key === "auto_policy" || change.key === "global_publish_min_interval_minutes" || change.key === "trends_authoring_min_volume" || change.key === "automatic_publication_operator_approved" || (((change.key === "auto_publishing_enabled" || originKey(change.key)) && change.value) || (change.key === "emergency_stop" && !change.value) || change.key === "google_account_available")) { setConfirmed(false); setLiveConfirmed(false); setPending(next); }
    else void save(next);
  }
  async function checkGoogle() {
    setBusy(true);
    try { const response = await fetch("/api/automation-controls/verify-google-readonly", { method: "POST" }); if (!response.ok) throw new Error("읽기 확인 요청 실패"); setToast("읽기 확인 완료 · 쓰기 가능 여부는 미검증"); await load(); }
    catch (err) { setToast(err instanceof Error ? err.message : "읽기 확인 실패"); } finally { setBusy(false); }
  }
  if (!data) return <section className={styles.card}><p role={error ? "alert" : "status"}>{error || "운영 설정을 불러오는 중입니다."}</p><button onClick={() => void load()}>다시 조회</button></section>;
  const state = data.settings;
  const minimumVolume = state.trends_authoring_min_volume ?? 5000;
  const approval = data.automatic_publication_approval ?? {
    approved: state.automatic_publication_operator_approved === true,
    effective: false,
    worker_applied: false,
    blockers: ["operator_approval_status_unavailable"],
    pending_auto_jobs: 0,
    legacy_operations_auto_approved: state.operations_auto_approved === true,
    configured_mode: state.configured_mode ?? "unknown",
    blogger_write_mode: state.blogger_write_mode ?? "unknown",
    external_cost_policy_approved: false,
    external_public_write_approved: false,
    scope: {},
    actor: state.automatic_publication_approval_actor ?? null,
    reason: state.automatic_publication_approval_reason ?? null,
    changed_at: state.automatic_publication_approval_changed_at ?? null,
  };
  return <section className={styles.root} aria-label="자동화 운영 설정">
    {error && <p role="alert" className={styles.toast}>조회 장애: {error} · 마지막 조회 상태이며 새 작업 허용을 보장하지 않습니다.</p>}
    {toast && <p role="status" className={styles.toast}>{toast}</p>}
    <div className={styles.form}><label>변경자<input value={actor} onChange={e => { setActor(e.target.value); setFormError(""); }} maxLength={100} /></label><label>변경 사유<input data-testid="automation-reason" value={reason} onChange={e => { setReason(e.target.value); setFormError(""); }} placeholder="운영 목적을 10자 이상 입력" maxLength={500} /></label></div>
    {formError && <p role="alert" className={styles.validation}>{formError}</p>}
    <div className={styles.grid}>{(Object.keys(title) as MainKey[]).map(key => <article key={key} className={styles.card} aria-label={title[key]}>
      <div className={styles.row}><h2>{title[key]}</h2><button type="button" className={styles.switch} role="switch" aria-label={title[key]} aria-checked={state[key]} disabled={busy || !!error} onClick={() => toggle({ key, value: !state[key] })}>{state[key] ? "ON" : "OFF"}</button></div>
      <p>설정: <strong>{state[key] ? "ON" : "OFF"}</strong></p><p className={styles.state}>적용 상태: {data.effective[key]}</p>
      {key === "trends_collection_enabled" && <><p>{state.interval_minutes}분 주기 · {data.recent.region_count}개 지역</p><p>최근 수집 {stamp(data.recent.last_collection)}</p><p className={styles.help}>OFF 기간의 누락 회차를 일괄 재실행하지 않습니다.</p></>}
      {key === "auto_manuscript_enabled" && <><p>작성 대기 {data.recent.authoring_queued}건 · 실행 중 {data.recent.authoring_running}건</p><p>최근 작성 {stamp(data.recent.last_authoring)}</p><p>최근 Import {stamp(data.recent.last_import)}</p><div className={styles.form}><label>Trends 검색량 기준 자동 작성<input data-testid="trends-authoring-min-volume" type="number" min={1} max={1000000000} step={1} value={volumeDraft} disabled={busy || !!error} onChange={event => { volumeDirty.current = true; setVolumeDraft(event.target.value); setFormError(""); }} /></label><div><p>자동 작성 기준: {minimumVolume.toLocaleString("ko-KR")} 이상 · 기본값 5,000</p><button type="button" disabled={busy || !!error || !/^\d+$/.test(volumeDraft) || Number(volumeDraft) < 1 || Number(volumeDraft) > 1000000000 || Number(volumeDraft) === minimumVolume} onClick={() => toggle({ key: "trends_authoring_min_volume", value: Number(volumeDraft) })}>작성 기준 변경</button></div></div><p className={styles.help}>Google Trends 검색량이 설정값 이상이면 중복 검사 후 원고 작성을 자동으로 요청합니다. 기준 미만 검색어는 기존 일반 선정 정책에 따라 처리됩니다. 검색량 기준은 원고 작성 요청의 우선 조건이며, 허위 정보 생성이나 발행 승인을 허용하지 않습니다.</p><p className={styles.help}>기준 이상: 중복 검사 후 작성 요청 · 기준 미만: 일반 선정 정책 적용</p><p className={styles.help}>기존 예약 원고: 영향 없음 · 수동 작성: 영향 없음</p></>}
      {key === "auto_publishing_enabled" && <>
        <p>공통 Blogger 발행 간격: 최소 {state.global_publish_min_interval_minutes}분 · 수동·Trends·예약·4개 블로그 전체</p>
        <div className={styles.form}><label>Blogger 전체 최소 발행 간격 (분)<input data-testid="global-interval" aria-label="Blogger 전체 최소 발행 간격 (분)" type="number" min={15} max={1440} step={1} value={intervalDraft} disabled={busy || !!error} onChange={event => { intervalDirty.current = true; setIntervalDraft(event.target.value); setFormError(""); }} /></label><div><p>현재 설정 {state.global_publish_min_interval_minutes}분 · 기본값 15분</p><p>KST 일일 LIVE 상한: {state.global_daily_live_publish_limit}건</p><button type="button" disabled={busy || !!error || !/^\d+$/.test(intervalDraft) || Number(intervalDraft) < 15 || Number(intervalDraft) > 1440 || Number(intervalDraft) === state.global_publish_min_interval_minutes} onClick={() => toggle({ key: "global_publish_min_interval_minutes", value: Number(intervalDraft) })}>발행 간격 변경</button></div></div>
        <div className={styles.origins}>{(Object.keys(originTitle) as (keyof typeof originTitle)[]).map(origin => <section key={origin} aria-label={originTitle[origin]}>
          <div className={styles.row}><h3>{originTitle[origin]}</h3><button type="button" role="switch" className={styles.switch} aria-label={originTitle[origin]} aria-checked={state[origin]} disabled={busy || !!error} onClick={() => toggle({ key: origin, value: !state[origin] })}>{state[origin] ? "ON" : "OFF"}</button></div>
          <p>설정: <strong>{state[origin] ? "ON" : "OFF"}</strong></p><p className={styles.state}>적용 상태: {data.effective[origin]}</p>
        </section>)}</div><p className={styles.help}>경로별 설정은 전체 OFF에서도 저장할 수 있습니다. 전체와 해당 경로가 모두 ON이어야 하며, 수동 작성·출처 불명 원고는 자동 발행하지 않습니다.</p>
        <label>자동 발행 방식<select disabled={busy} value={mode} onChange={e => { policyDirty.current = true; setMode(e.target.value as "draft" | "publish"); }}><option value="draft">Draft 비공개 저장</option><option value="publish">LIVE 공개</option></select></label><p>저장된 방식: {state.auto_mode === "draft" ? "Draft" : "LIVE"} · 실행 자격 Job {data.eligible_jobs}건</p><div className={styles.targets} aria-label="자동 발행 대상">{data.blogs.length ? data.blogs.map(blog => <label key={blog.id}><input type="checkbox" disabled={busy} checked={blogs.includes(blog.id)} onChange={e => { policyDirty.current = true; setBlogs(current => e.target.checked ? [...current, blog.id] : current.filter(x => x !== blog.id)); }} />{blog.display_name} · {blog.language_code}</label>) : <p>활성 Blogger가 없습니다.</p>}</div><button type="button" disabled={busy || !!error || (mode === state.auto_mode && JSON.stringify([...blogs].sort()) === JSON.stringify([...state.auto_blog_ids].sort()))} onClick={() => toggle({ key: "auto_policy" })}>발행 방식·대상 저장</button><p className={styles.help}>기존 failed·보류·대기 Job은 다시 승인되지 않습니다. 설정 이후 신규 적격 버전만 검사합니다.</p></>}
      {key === "manual_publishing_enabled" && <><p>관리자 직접 요청: {state.manual_publishing_enabled ? "사용 허용" : "사용 중지"}</p><p>최근 게시 {data.last_publication?.remote_status ?? "기록 없음"} · {stamp(data.last_publication?.remote_verified_at)}</p><p className={styles.help}>LIVE 최종 확인과 정확한 원고 버전 확인을 유지합니다. 복사·다운로드·편집은 계속 사용할 수 있습니다.</p></>}
    </article>)}</div>
    <article className={styles.card} aria-label="자동 발행 운영 허용">
      <div className={styles.row}><h2>자동 발행 운영 허용</h2><button type="button" className={styles.switch} role="switch" aria-label="자동 발행 운영 허용" aria-checked={state.automatic_publication_operator_approved} disabled={busy || !!error} onClick={() => toggle({ key: "automatic_publication_operator_approved", value: !state.automatic_publication_operator_approved })}>{state.automatic_publication_operator_approved ? "ON" : "OFF"}</button></div>
      <p>설정: <strong>{approval.approved ? "ON" : "OFF"}</strong></p>
      <p className={styles.state}>실제 적용 상태: {data.effective.automatic_publication_operator_approved}</p>
      <p>Publication Worker 적용: {approval.worker_applied ? "확인됨" : "적용 대기 또는 heartbeat 확인 필요"} · revision {data.workers.find(worker => worker.service_name === "publication_worker")?.applied_revision ?? "확인 불가"}</p>
      <p>전체 자동 발행 {state.auto_publishing_enabled ? "ON" : "OFF"} · Trends {state.trends_auto_publishing_enabled ? "ON" : "OFF"} · 예약 {state.scheduled_auto_publishing_enabled ? "ON" : "OFF"}</p>
      <p>발행 방식 {state.auto_mode === "publish" ? "LIVE" : "Draft"} · 글로벌 간격 {state.global_publish_min_interval_minutes}분 · 일일 LIVE 상한 {state.global_daily_live_publish_limit}건</p>
      <p>긴급 정지 {state.emergency_stop ? "ON" : "OFF"} · Blogger API 제한 {state.blogger_api_restricted ? "감지됨" : "감지되지 않음"} · 대기 자동 Job {approval.pending_auto_jobs}건</p>
      <p>외부 0원 비용 승인 {approval.external_cost_policy_approved ? "확인됨" : "미확인"} · 외부 공개 쓰기 승인 {approval.external_public_write_approved ? "확인됨" : "미확인"} · 쓰기 모드 {approval.blogger_write_mode}</p>
      {approval.blockers.length > 0 && <p className={styles.help}>차단 사유: {approval.blockers.join(", ")}</p>}
      <p>마지막 변경: {approval.actor ?? "기록 없음"} · {stamp(approval.changed_at)}</p>
      <p className={styles.help}>운영 승인은 자동 발행의 추가 관리 조건입니다. OAuth, 외부 쓰기 승인, 0원 정책, 긴급 정지, 적격성, 간격 및 일일 상한 검사를 변경하거나 우회하지 않습니다. OFF여도 수동 발행 설정은 별도로 유지됩니다.</p>
    </article>
    <article className={styles.card}><div className={styles.row}><h2>Blogger 긴급 정지</h2><button className={styles.switch} role="switch" aria-label="Blogger 긴급 정지" aria-checked={state.emergency_stop} disabled={busy || !!error} onClick={() => toggle({ key: "emergency_stop", value: !state.emergency_stop })}>{state.emergency_stop ? "ON" : "OFF"}</button></div><p>{state.emergency_stop ? "자동·수동 API 쓰기를 모두 차단합니다." : "해제 상태입니다. 각 발행 설정과 개별 게시 조건은 별도로 검사합니다."}</p></article>
    <article className={styles.card}><h2>Google API 접근 상태</h2><p>계정 상태 신고: {state.google_account_report === "user_reported_available" ? "사용자가 제한 해제 확인" : state.google_account_report === "restricted" ? "제한 신고됨" : "확인되지 않음"}</p><p>프로젝트 제한 게이트: {state.blogger_api_restricted ? "차단" : "해제"}</p><p>읽기 검사 {stamp(state.read_check_result.checked_at)}</p>{state.read_check_result.results?.map(row => <p key={row.blog_id}>{data.blogs.find(b => b.id === row.blog_id)?.display_name ?? row.blog_id}: {row.read_available ? "읽기 성공" : `읽기 확인 실패 · ${row.reason ?? "원인 확인 필요"}`}</p>)}<p><strong>실제 쓰기 가능 여부: 미검증</strong></p><p className={styles.help}>제한 해제 신고와 읽기 성공은 쓰기 권한·쓰기 성공을 입증하지 않습니다. 이 화면에서 테스트 게시물을 만들지 않습니다.</p><div className={styles.buttons}><button disabled={busy || !!error} onClick={() => void checkGoogle()}>읽기 전용 확인</button><button disabled={busy || !!error} onClick={() => toggle({ key: "google_account_available", value: state.blogger_api_restricted })}>계정 제한 신고 변경</button></div></article>
    <section className={styles.card}><h2>Worker 적용 확인</h2><p>저장된 설정 revision {state.revision} · 최종 저장 {stamp(state.updated_at)}</p>{data.workers.map(worker => <p key={worker.service_name}>{worker.service_name} · PID {worker.process_id} · 적용 revision {worker.applied_revision ?? "확인 불가"} · {worker.policy_applied ? "Worker 적용 확인" : "적용 대기 또는 heartbeat 확인 필요"} · {stamp(worker.policy_seen_at)}</p>)}</section>
    <section className={`${styles.card} ${styles.history}`}><h2>설정 변경 이력</h2>{data.history.length ? <table><thead><tr><th>시각</th><th>변경자·사유</th><th>변경 내용</th></tr></thead><tbody>{data.history.map(event => <tr key={event.id}><td>{stamp(event.created_at)}</td><td>{event.payload.actor}<br />{event.payload.reason}</td><td>{event.payload.changes.map((change, index) => <div key={`${change.key}-${index}`}>{change.key}: {JSON.stringify(change.before)} → {JSON.stringify(change.after)}</div>)}</td></tr>)}</tbody></table> : <p>변경 이력이 없습니다.</p>}</section>
    <dialog ref={dialog} className={styles.dialog} onCancel={() => setPending(null)}>
      <h2>{pending?.key === "automatic_publication_operator_approved" ? "\uc790\ub3d9 \ubc1c\ud589 \uc6b4\uc601 \uc2b9\uc778 \ud655\uc778" : pending?.key === "trends_authoring_min_volume" ? "Trends 원고 작성 검색량 기준 변경 확인" : pending?.key === "global_publish_min_interval_minutes" ? "Global publication interval confirmation" : pending && originKey(pending.key) ? `${originTitle[pending.key]} confirmation` : (pending?.key === "auto_publishing_enabled" || pending?.key === "auto_policy") ? "Automatic publication confirmation" : pending?.key === "emergency_stop" ? "Emergency stop release confirmation" : "Account restriction report confirmation"}</h2>
      {pending?.key === "automatic_publication_operator_approved" ? <>
        <p>{"\uc790\ub3d9 \ubc1c\ud589 \uc6b4\uc601 \uc2b9\uc778 "}{pending.value ? "ON" : "OFF"}{"\uc744 \uc694\uccad\ud569\ub2c8\ub2e4. \uc774 \uc124\uc815\uc740 \uc804\uccb4 \uc790\ub3d9 \ubc1c\ud589, Blogger \uc678\ubd80 \uc4f0\uae30 \uad8c\ud55c \ub610\ub294 \ube44\uc6a9 \uc815\ucc45 \uc2b9\uc778\uc744 \ub300\uc2e0\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4."}</p>
        <ul>
          <li>{"\uc804\uccb4 \uc790\ub3d9 \ubc1c\ud589: "}{state.auto_publishing_enabled ? "ON" : "OFF"}</li>
          <li>{"Trends \uc790\ub3d9 \ubc1c\ud589: "}{state.trends_auto_publishing_enabled ? "ON" : "OFF"}</li>
          <li>{"\uc608\uc57d \uc790\ub3d9 \ubc1c\ud589: "}{state.scheduled_auto_publishing_enabled ? "ON" : "OFF"}</li>
          <li>{"\ubc1c\ud589 \ubc29\uc2dd: "}{state.auto_mode === "publish" ? "LIVE" : "Draft"}</li>
          <li>{"\uae00\ub85c\ubc8c \ucd5c\uc18c \uac04\uaca9: "}{state.global_publish_min_interval_minutes}{"\ubd84 \u00b7 \uc77c\uc77c LIVE \uc0c1\ud55c: "}{state.global_daily_live_publish_limit}{"\uac74"}</li>
          <li>{"\uae34\uae09 \uc815\uc9c0: "}{state.emergency_stop ? "ON" : "OFF"}{" \u00b7 API \uc81c\ud55c: "}{state.blogger_api_restricted ? "\uac10\uc9c0\ub428" : "\uac10\uc9c0\ub418\uc9c0 \uc54a\uc74c"}</li>
          <li>{"\uae30\uc874 \uc790\ub3d9 \ub300\uae30 Job: "}{approval.pending_auto_jobs}{"\uac74. \uae30\uc874 Job\uc740 \uc7ac\uc2b9\uc778\ud558\uac70\ub098 \uc7ac\uc2e4\ud589\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4."}</li>
        </ul>
        <p className={styles.help}>{"\uc2e0\uaddc \uc6d0\uace0\ub3c4 \uacbd\ub85c\ubcc4 \uc124\uc815, Blogger \uad8c\ud55c, \uc678\ubd80 \uc2b9\uc778, 0\uc6d0 \uc815\ucc45, \uc911\ubcf5\u00b7\ud3d0\uae30\u00b7\ud488\uc9c8 \uac80\uc0ac, \ubc1c\ud589 \uac04\uaca9 \ubc0f \uc77c\uc77c \uc0c1\ud55c\uc744 \uac01\uac01 \ud1b5\uacfc\ud574\uc57c \ud569\ub2c8\ub2e4."}</p>
      </> : <p>{pending?.key === "trends_authoring_min_volume" ? `새 수집 회차의 Trends 원고 작성 최소 검색량을 ${pending.value.toLocaleString("ko-KR")}으로 변경합니다. 기존 작성 요청과 수집 이력은 유지합니다.` : pending?.key === "global_publish_min_interval_minutes" ? `The global minimum interval will change to ${pending.value} minutes. Completed publications and in-flight requests are not rewritten.` : pending && originKey(pending.key) ? `${originTitle[pending.key]} will be enabled. Existing jobs will not be resumed.` : (pending?.key === "auto_publishing_enabled" || pending?.key === "auto_policy") ? `${mode === "publish" ? "LIVE" : "Draft"} ? ${blogs.length} selected blogs. Only new eligible manuscripts are considered.` : pending?.key === "emergency_stop" ? `Global automatic publication is ${state.auto_publishing_enabled ? "ON" : "OFF"}. Releasing the stop does not change that setting.` : "This changes only the account restriction report. Read access does not prove write permission."}</p>}
      <div className={styles.form}><label>Actor<input value={actor} onChange={e => { setActor(e.target.value); setFormError(""); }} maxLength={100} /></label><label>Reason<input data-testid="automation-reason" value={reason} onChange={e => { setReason(e.target.value); setFormError(""); }} maxLength={500} /></label></div>
      <p className={styles.help}>Actor must contain at least 2 characters; reason must contain at least 10.</p>
      {formError && <p role="alert" className={styles.validation}>{formError}</p>}{saveError && <p role="alert" className={styles.validation}>{saveError}</p>}
      <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{pending?.key === "automatic_publication_operator_approved" ? "\ud45c\uc2dc\ub41c \uc6b4\uc601 \uc2b9\uc778 \ubc94\uc704\uc640 \uae30\uc874 Job \ubcf4\ud638 \uc815\ucc45\uc744 \ud655\uc778\ud588\uc2b5\ub2c8\ub2e4." : "I confirm this target and its scope."}</label>
      {pending && ((pending.key === "auto_publishing_enabled" || pending.key === "auto_policy") ? mode === "publish" : originKey(pending.key) && state.auto_mode === "publish") && <label><input type="checkbox" checked={liveConfirmed} onChange={e => setLiveConfirmed(e.target.checked)} />Confirm LIVE automatic publishing separately.</label>}
      <div className={styles.buttons}><button disabled={busy || !confirmed || actor.trim().length < 2 || reason.trim().length < 10 || (((pending?.key === "auto_publishing_enabled" || pending?.key === "auto_policy") && (!blogs.length || (mode === "publish" && !liveConfirmed))) || (!!pending && originKey(pending.key) && state.auto_mode === "publish" && !liveConfirmed))} onClick={() => pending && void save(pending, true)}>{busy ? "Saving…" : pending?.key === "automatic_publication_operator_approved" ? "\ud655\uc778 \ud6c4 \uc801\uc6a9" : "Confirm and apply"}</button><button disabled={busy} onClick={() => setPending(null)}>Cancel</button></div>
    </dialog>
  </section>;
}
