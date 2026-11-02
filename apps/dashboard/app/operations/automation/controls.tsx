"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./controls.module.css";

type MainKey = "trends_collection_enabled" | "auto_manuscript_enabled" | "auto_publishing_enabled" | "manual_publishing_enabled";
type Key = MainKey | "trends_auto_publishing_enabled" | "scheduled_auto_publishing_enabled";
type Settings = Record<Key, boolean> & { revision: number; emergency_stop: boolean; blogger_api_restricted: boolean; interval_minutes: number; global_publish_min_interval_minutes: number; auto_mode: "draft" | "publish"; auto_blog_ids: string[]; google_account_report: string; read_check_result: { checked_at?: string; results?: { blog_id: string; read_available: boolean; reason?: string }[] } };
type Change = { key: Key | "emergency_stop" | "google_account_available"; value: boolean; revision?: number } | { key: "auto_policy"; revision?: number };
type Snapshot = { settings: Settings & { updated_at?: string }; effective: Record<Key, string>; workers: { service_name: string; process_id: number; policy_applied: boolean; applied_revision?: number; engine_version?: string; policy_seen_at?: string }[]; history: { id: number; created_at: string; payload: { actor: string; reason: string; changes: { key: string; before: unknown; after: unknown }[] } }[]; blogs: { id: string; display_name: string; language_code: string }[]; recent: { last_collection: string | null; last_import: string | null; last_authoring: string | null; authoring_queued: number; authoring_running: number; region_count: number }; eligible_jobs: number; last_publication: { remote_status: string; remote_verified_at: string } | null };
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
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState<"draft" | "publish">("draft");
  const [blogs, setBlogs] = useState<string[]>([]);
  const [pending, setPending] = useState<Change | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [liveConfirmed, setLiveConfirmed] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const awaiting = useRef<number | null>(null);
  const initialized = useRef(false);
  const policyDirty = useRef(false);
  const lastRevision = useRef(0);
  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/automation-controls", { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? result.detail ?? "운영 설정을 조회할 수 없습니다.");
      const snapshot = result as Snapshot;
      if (snapshot.settings.revision < lastRevision.current) return;
      lastRevision.current = snapshot.settings.revision;
      if (!initialized.current || !policyDirty.current) { setMode(snapshot.settings.auto_mode); setBlogs(snapshot.settings.auto_blog_ids); initialized.current = true; }
      setData(current => !current || snapshot.settings.revision >= current.settings.revision ? snapshot : current); setError("");
      if (awaiting.current !== null && snapshot.settings.revision >= awaiting.current && ["research_worker", "publication_worker"].every(service => snapshot.workers.some(w => w.service_name === service && w.policy_applied && w.applied_revision === awaiting.current))) { setToast(snapshot.settings.emergency_stop ? "Worker 적용 확인 · 긴급 정지로 발행 차단" : "Worker 적용 확인"); awaiting.current = null; }
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
      const response = await fetch("/api/automation-controls", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: change.revision ?? data.settings.revision, actor: actor.trim(), reason: reason.trim(), ...(change.key === "auto_policy" ? { auto_mode: mode, auto_blog_ids: blogs } : { [change.key]: change.value }), ...(change.key !== "auto_policy" && originKey(change.key) && change.value ? { confirm_auto: confirmation, confirm_live: liveConfirmed } : {}), ...(auto ? { auto_mode: mode, auto_blog_ids: blogs, confirm_auto: confirmation, confirm_live: liveConfirmed } : {}), ...(policy ? { confirm_auto: confirmation, confirm_live: liveConfirmed } : {}), confirm_emergency_release: change.key === "emergency_stop" && !change.value && confirmation }) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : result.error ?? "설정 변경에 실패했습니다.");
      lastRevision.current = result.revision; awaiting.current = result.revision; policyDirty.current = false; setToast("설정 저장 완료 · Worker 적용 대기"); setPending(null); window.dispatchEvent(new Event("woori-automation-policy-changed")); await load();
    } catch (err) { const message = `설정 변경 실패: ${err instanceof Error ? err.message : "다시 시도하세요."}`; setSaveError(message); setToast(message); if (err instanceof Error && err.message.includes("최신 상태")) { policyDirty.current = false; setPending(null); await load(); } } finally { setBusy(false); }
  }
  function toggle(change: Change) {
    if (busy || !data) return;
    if (actor.trim().length < 2 || reason.trim().length < 10) { setFormError("변경자는 2자 이상, 변경 사유는 10자 이상 입력하세요."); return; }
    setFormError(""); setSaveError("");
    const next = { ...change, revision: data.settings.revision };
    if (change.key === "auto_policy" || (((change.key === "auto_publishing_enabled" || originKey(change.key)) && change.value) || (change.key === "emergency_stop" && !change.value) || change.key === "google_account_available")) { setConfirmed(false); setLiveConfirmed(false); setPending(next); }
    else void save(next);
  }
  async function checkGoogle() {
    setBusy(true);
    try { const response = await fetch("/api/automation-controls/verify-google-readonly", { method: "POST" }); if (!response.ok) throw new Error("읽기 확인 요청 실패"); setToast("읽기 확인 완료 · 쓰기 가능 여부는 미검증"); await load(); }
    catch (err) { setToast(err instanceof Error ? err.message : "읽기 확인 실패"); } finally { setBusy(false); }
  }
  if (!data) return <section className={styles.card}><p role={error ? "alert" : "status"}>{error || "운영 설정을 불러오는 중입니다."}</p><button onClick={() => void load()}>다시 조회</button></section>;
  const state = data.settings;
  return <section className={styles.root} aria-label="자동화 운영 설정">
    {error && <p role="alert" className={styles.toast}>조회 장애: {error} · 마지막 조회 상태이며 새 작업 허용을 보장하지 않습니다.</p>}
    {toast && <p role="status" className={styles.toast}>{toast}</p>}
    <div className={styles.form}><label>변경자<input value={actor} onChange={e => { setActor(e.target.value); setFormError(""); }} maxLength={100} /></label><label>변경 사유<input value={reason} onChange={e => { setReason(e.target.value); setFormError(""); }} placeholder="운영 목적을 10자 이상 입력" maxLength={500} /></label></div>
    {formError && <p role="alert" className={styles.validation}>{formError}</p>}
    <div className={styles.grid}>{(Object.keys(title) as MainKey[]).map(key => <article key={key} className={styles.card} aria-label={title[key]}>
      <div className={styles.row}><h2>{title[key]}</h2><button type="button" className={styles.switch} role="switch" aria-label={title[key]} aria-checked={state[key]} disabled={busy || !!error} onClick={() => toggle({ key, value: !state[key] })}>{state[key] ? "ON" : "OFF"}</button></div>
      <p>설정: <strong>{state[key] ? "ON" : "OFF"}</strong></p><p className={styles.state}>적용 상태: {data.effective[key]}</p>
      {key === "trends_collection_enabled" && <><p>{state.interval_minutes}분 주기 · {data.recent.region_count}개 지역</p><p>최근 수집 {stamp(data.recent.last_collection)}</p><p className={styles.help}>OFF 기간의 누락 회차를 일괄 재실행하지 않습니다.</p></>}
      {key === "auto_manuscript_enabled" && <><p>작성 대기 {data.recent.authoring_queued}건 · 실행 중 {data.recent.authoring_running}건</p><p>최근 작성 {stamp(data.recent.last_authoring)}</p><p>최근 Import {stamp(data.recent.last_import)}</p><p className={styles.help}>예약 15개와 Trends 자동 작성에 적용합니다. 수동 작성·편집·기존 Import는 보존합니다.</p></>}
      {key === "auto_publishing_enabled" && <>
        <p>공통 Blogger 발행 간격: 최소 {state.global_publish_min_interval_minutes}분 · 수동·Trends·예약·4개 블로그 전체</p>
        <div className={styles.origins}>{(Object.keys(originTitle) as (keyof typeof originTitle)[]).map(origin => <section key={origin} aria-label={originTitle[origin]}>
          <div className={styles.row}><h3>{originTitle[origin]}</h3><button type="button" role="switch" className={styles.switch} aria-label={originTitle[origin]} aria-checked={state[origin]} disabled={busy || !!error} onClick={() => toggle({ key: origin, value: !state[origin] })}>{state[origin] ? "ON" : "OFF"}</button></div>
          <p>설정: <strong>{state[origin] ? "ON" : "OFF"}</strong></p><p className={styles.state}>적용 상태: {data.effective[origin]}</p>
        </section>)}</div><p className={styles.help}>경로별 설정은 전체 OFF에서도 저장할 수 있습니다. 전체와 해당 경로가 모두 ON이어야 하며, 수동 작성·출처 불명 원고는 자동 발행하지 않습니다.</p>
        <label>자동 발행 방식<select disabled={busy} value={mode} onChange={e => { policyDirty.current = true; setMode(e.target.value as "draft" | "publish"); }}><option value="draft">Draft 비공개 저장</option><option value="publish">LIVE 공개</option></select></label><p>저장된 방식: {state.auto_mode === "draft" ? "Draft" : "LIVE"} · 실행 자격 Job {data.eligible_jobs}건</p><div className={styles.targets} aria-label="자동 발행 대상">{data.blogs.length ? data.blogs.map(blog => <label key={blog.id}><input type="checkbox" disabled={busy} checked={blogs.includes(blog.id)} onChange={e => { policyDirty.current = true; setBlogs(current => e.target.checked ? [...current, blog.id] : current.filter(x => x !== blog.id)); }} />{blog.display_name} · {blog.language_code}</label>) : <p>활성 Blogger가 없습니다.</p>}</div><button type="button" disabled={busy || !!error || (mode === state.auto_mode && JSON.stringify([...blogs].sort()) === JSON.stringify([...state.auto_blog_ids].sort()))} onClick={() => toggle({ key: "auto_policy" })}>발행 방식·대상 저장</button><p className={styles.help}>기존 failed·보류·대기 Job은 다시 승인되지 않습니다. 설정 이후 신규 적격 버전만 검사합니다.</p></>}
      {key === "manual_publishing_enabled" && <><p>관리자 직접 요청: {state.manual_publishing_enabled ? "사용 허용" : "사용 중지"}</p><p>최근 게시 {data.last_publication?.remote_status ?? "기록 없음"} · {stamp(data.last_publication?.remote_verified_at)}</p><p className={styles.help}>LIVE 최종 확인과 정확한 원고 버전 확인을 유지합니다. 복사·다운로드·편집은 계속 사용할 수 있습니다.</p></>}
    </article>)}</div>
    <article className={styles.card}><div className={styles.row}><h2>Blogger 긴급 정지</h2><button className={styles.switch} role="switch" aria-label="Blogger 긴급 정지" aria-checked={state.emergency_stop} disabled={busy || !!error} onClick={() => toggle({ key: "emergency_stop", value: !state.emergency_stop })}>{state.emergency_stop ? "ON" : "OFF"}</button></div><p>{state.emergency_stop ? "자동·수동 API 쓰기를 모두 차단합니다." : "해제 상태입니다. 각 발행 설정과 개별 게시 조건은 별도로 검사합니다."}</p></article>
    <article className={styles.card}><h2>Google API 접근 상태</h2><p>계정 상태 신고: {state.google_account_report === "user_reported_available" ? "사용자가 제한 해제 확인" : state.google_account_report === "restricted" ? "제한 신고됨" : "확인되지 않음"}</p><p>프로젝트 제한 게이트: {state.blogger_api_restricted ? "차단" : "해제"}</p><p>읽기 검사 {stamp(state.read_check_result.checked_at)}</p>{state.read_check_result.results?.map(row => <p key={row.blog_id}>{data.blogs.find(b => b.id === row.blog_id)?.display_name ?? row.blog_id}: {row.read_available ? "읽기 성공" : `읽기 확인 실패 · ${row.reason ?? "원인 확인 필요"}`}</p>)}<p><strong>실제 쓰기 가능 여부: 미검증</strong></p><p className={styles.help}>제한 해제 신고와 읽기 성공은 쓰기 권한·쓰기 성공을 입증하지 않습니다. 이 화면에서 테스트 게시물을 만들지 않습니다.</p><div className={styles.buttons}><button disabled={busy || !!error} onClick={() => void checkGoogle()}>읽기 전용 확인</button><button disabled={busy || !!error} onClick={() => toggle({ key: "google_account_available", value: state.blogger_api_restricted })}>계정 제한 신고 변경</button></div></article>
    <section className={styles.card}><h2>Worker 적용 확인</h2><p>저장된 설정 revision {state.revision} · 최종 저장 {stamp(state.updated_at)}</p>{data.workers.map(worker => <p key={worker.service_name}>{worker.service_name} · PID {worker.process_id} · 적용 revision {worker.applied_revision ?? "확인 불가"} · {worker.policy_applied ? "Worker 적용 확인" : "적용 대기 또는 heartbeat 확인 필요"} · {stamp(worker.policy_seen_at)}</p>)}</section>
    <section className={`${styles.card} ${styles.history}`}><h2>설정 변경 이력</h2>{data.history.length ? <table><thead><tr><th>시각</th><th>변경자·사유</th><th>변경 내용</th></tr></thead><tbody>{data.history.map(event => <tr key={event.id}><td>{stamp(event.created_at)}</td><td>{event.payload.actor}<br />{event.payload.reason}</td><td>{event.payload.changes.map((change, index) => <div key={`${change.key}-${index}`}>{change.key}: {JSON.stringify(change.before)} → {JSON.stringify(change.after)}</div>)}</td></tr>)}</tbody></table> : <p>변경 이력이 없습니다.</p>}</section>
    <dialog ref={dialog} className={styles.dialog} onCancel={() => setPending(null)}><h2>{pending && originKey(pending.key) ? `${originTitle[pending.key]} 확인` : (pending?.key === "auto_publishing_enabled" || pending?.key === "auto_policy") ? "자동 발행 최종 확인" : pending?.key === "emergency_stop" ? "긴급 정지 해제 확인" : "계정 제한 신고 확인"}</h2><p>{pending && originKey(pending.key) ? `${originTitle[pending.key]}을 허용합니다. 저장된 방식: ${state.auto_mode === "publish" ? "LIVE" : "Draft"}. 전체 자동 발행은 현재 ${state.auto_publishing_enabled ? "ON" : "OFF"}이며 별도로 유지됩니다. 경로 활성화 이후 새로 완료된 적격 Import만 검토하며 기존 Job은 재개하지 않습니다.` : (pending?.key === "auto_publishing_enabled" || pending?.key === "auto_policy") ? `${mode === "publish" ? "LIVE 공개" : "Draft 비공개 저장"} · 선택한 Blogger ${blogs.length}개. 활성화 이후 신규 적격 원고만 중복·품질 검사를 거쳐 처리합니다. 기존 Job은 재개하지 않습니다.` : pending?.key === "emergency_stop" ? `자동 발행 설정은 현재 ${state.auto_publishing_enabled ? "ON" : "OFF"}입니다. 긴급 정지 해제는 이 설정을 변경하지 않습니다.` : "계정 제한 신고만 변경합니다. 긴급 정지와 자동 발행 설정은 변경하지 않으며 실제 쓰기는 검증되지 않습니다."}</p><div className={styles.form}><label>확인 변경자<input value={actor} onChange={e => setActor(e.target.value)} maxLength={100} /></label><label>확인 변경 사유<input value={reason} onChange={e => setReason(e.target.value)} maxLength={500} /></label></div><p className={styles.help}>변경자 2자, 변경 사유 10자 이상을 입력하세요.</p>{formError && <p role="alert" className={styles.validation}>{formError}</p>}{saveError && <p role="alert" className={styles.validation}>{saveError}</p>}<label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />대상과 적용 범위를 확인했습니다.</label>{pending && ((pending.key === "auto_publishing_enabled" || pending.key === "auto_policy") ? mode === "publish" : originKey(pending.key) && state.auto_mode === "publish") && <label><input type="checkbox" checked={liveConfirmed} onChange={e => setLiveConfirmed(e.target.checked)} />LIVE 자동 공개를 별도로 승인합니다.</label>}<div className={styles.buttons}><button disabled={busy || !confirmed || actor.trim().length < 2 || reason.trim().length < 10 || (((pending?.key === "auto_publishing_enabled" || pending?.key === "auto_policy") && (!blogs.length || (mode === "publish" && !liveConfirmed))) || (!!pending && originKey(pending.key) && state.auto_mode === "publish" && !liveConfirmed))} onClick={() => pending && void save(pending, true)}>확인 후 적용</button><button disabled={busy} onClick={() => setPending(null)}>취소</button></div></dialog>
  </section>;
}
