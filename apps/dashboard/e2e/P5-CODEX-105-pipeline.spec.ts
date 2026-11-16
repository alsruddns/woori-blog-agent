import { test, expect } from "playwright/test";

const run = (stage: string, status: string, id: string) => ({ id, stage, status, scope_key: "2026-11-02T10:00:00+09:00", engine_version: "isolated-fixture/1", settings_id: 1, checkpoint: "scores_saved", owner_pid: 105, attempt: 1, processed: 20, remaining: 0, last_progress_at: "2026-11-02T10:00:20+09:00", elapsed_ms: status === "running" ? null : 250, stalled_suspected: status === "running", error_category: null, result: { regions: 11, successes: 11, failures: 0 } });
const fixture = () => ({ health: "collection_delayed", settings: { collection_enabled: true, authoring_enabled: true }, last_attempt: "2026-11-02T10:00:00+09:00", last_success: "2026-11-02T02:10:00+09:00", interval_minutes: 30, regions: 11, collection_delayed: true, runs: [run("trends_collection", "completed", "collection-fixture"), run("topic_evaluation", "running", "evaluation-fixture")], means: [{ stage: "topic_evaluation", mean_ms: 250 }], authoring: [{ state: "import_pending", n: 1, progress_at: null }], imports: { n: 1, latest: null }, quality: [{ stage: "static", status: "completed", n: 1 }], usage_signal: { active: true, error_code: "codex_usage_limit", not_before: "2026-11-02T10:15:00+09:00" } });
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("woori-theme", "dark"));
  await page.route("**/api/research/editorial-intelligence/pipeline", route => route.fulfill({ json: fixture() }));
});

test("separate progress, quota and delayed collection at desktop/mobile", async ({ page }, info) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/operations/research");
  const monitor = page.getByRole("region", { name: "연구 파이프라인 모니터" });
  await expect(monitor.getByText("데이터 수집 정체 의심", { exact: false })).toBeVisible();
  await expect(monitor.getByText("주제 평가 · 진행 지연 의심", { exact: true })).toBeVisible();
  await expect(monitor.getByText("작성 완료 · Import 대기: 1건", { exact: true })).toBeVisible();
  await expect(monitor.getByText("정적 평가 · 완료: 1건", { exact: true })).toBeVisible();
  await expect(monitor.getByText("제공자 초기화 시각은 미확인", { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await monitor.screenshot({ path: `../../docs/development/assets/P5-CODEX-105-monitor-${info.project.name}.png` });
});

test("stage and status filters plus Job search", async ({ page }) => {
  await page.goto("/operations/research");
  const monitor = page.getByRole("region", { name: "연구 파이프라인 모니터" });
  await monitor.getByRole("combobox", { name: "단계", exact: true }).selectOption("topic_evaluation");
  await expect(monitor.getByText("Job collection-fixture")).toHaveCount(0);
  await expect(monitor.getByText("Job evaluation-fixture")).toBeVisible();
  await monitor.getByRole("combobox", { name: "처리 상태", exact: true }).selectOption("completed");
  await expect(monitor.getByText("조건에 맞는 단계 실행 기록이 없습니다.")).toBeVisible();
  await monitor.getByRole("combobox", { name: "처리 상태", exact: true }).selectOption("");
  await monitor.getByLabel("회차·Job 검색").fill("missing-job");
  await expect(monitor.getByText("조건에 맞는 단계 실행 기록이 없습니다.")).toBeVisible();
});

test("empty history never fabricates completed evaluations", async ({ page }) => {
  await page.route("**/api/research/editorial-intelligence/pipeline", route => route.fulfill({ json: { ...fixture(), runs: [], means: [], authoring: [], quality: [] } }));
  await page.goto("/operations/research");
  const monitor = page.getByRole("region", { name: "연구 파이프라인 모니터" });
  await expect(monitor.getByText("평가 실행 기록 없음 · 수집 완료 대기")).toBeVisible();
  await expect(monitor.getByText("작성 Job 없음")).toBeVisible();
});

test("API failure is visible and not a healthy heartbeat", async ({ page }) => {
  await page.route("**/api/research/editorial-intelligence/pipeline", route => route.fulfill({ status: 503, json: { error: "isolated unavailable" } }));
  await page.goto("/operations/research");
  await expect(page.getByRole("alert").filter({ hasText: "파이프라인 상태를 확인할 수 없습니다." })).toBeVisible();
});
