import { test, expect } from "playwright/test";

test.beforeEach(async ({ page }) => {
  const state = { revision: 1, trends_collection_enabled: true, auto_manuscript_enabled: true, auto_publishing_enabled: false, trends_auto_publishing_enabled: false, scheduled_auto_publishing_enabled: false, manual_publishing_enabled: true, emergency_stop: true, blogger_api_restricted: true, interval_minutes: 10, auto_mode: "draft", auto_blog_ids: [] as string[], google_account_report: "unverified", read_check_result: {} };
  await page.route("**/api/automation-controls**", async route => {
    const request = route.request();
    if (request.method() === "PUT") {
      const value = request.postDataJSON();
      for (const key of Object.keys(state)) if (key in value && key !== "revision") Object.assign(state, { [key]: value[key] });
      if (value.google_account_available !== undefined) { state.blogger_api_restricted = !value.google_account_available; state.google_account_report = "user_reported_available"; }
      state.revision++;
      return route.fulfill({ json: { saved: true, revision: state.revision, application: "pending_worker_ack" } });
    }
    if (request.method() === "POST") return route.fulfill({ json: { write_verified: false } });
    return route.fulfill({ json: { settings: state, effective: Object.fromEntries(["trends_collection_enabled", "auto_manuscript_enabled", "auto_publishing_enabled", "manual_publishing_enabled", "trends_auto_publishing_enabled", "scheduled_auto_publishing_enabled"].map(key => [key, !state[key as keyof typeof state] ? "신규 실행 중지" : ["trends_auto_publishing_enabled", "scheduled_auto_publishing_enabled"].includes(key) && !state.auto_publishing_enabled ? "전체 자동 발행 OFF로 차단 중" : key.includes("publishing") && state.emergency_stop ? "긴급 정지로 차단" : "정상"])), workers: [{ service_name: "research_worker", process_id: 101, policy_applied: true }, { service_name: "publication_worker", process_id: 102, policy_applied: true }], history: [], blogs: [{ id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa", display_name: "English Blogger", language_code: "en" }], recent: { region_count: 11, last_collection: "2026-11-01T16:00:00Z", last_import: null, last_authoring: null, authoring_queued: 2, authoring_running: 0 }, eligible_jobs: 0, last_publication: null } });
  });
});

test("seven controls, independent OFF and responsive state", async ({ page }, info) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/operations/automation");
  await expect(page.getByRole("heading", { name: "자동화 운영 제어센터" })).toBeVisible();
  await expect(page.getByRole("switch")).toHaveCount(7);
  await expect(page.getByText("10분 주기 · 11개 지역")).toBeVisible();
  await page.getByLabel("변경 사유", { exact: true }).fill("격리 화면에서 수집 중지 독립 설정 확인");
  await page.getByRole("switch", { name: "Google Trends 수집" }).click();
  await expect(page.getByRole("switch", { name: "Google Trends 수집" })).toHaveAttribute("aria-checked", "false");
  await expect(page.getByRole("switch", { name: "Codex 자동 원고 작성" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("switch", { name: "Blogger 자동 발행" })).toHaveAttribute("aria-checked", "false");
  await expect(page.getByRole("switch", { name: "Blogger 수동 발행" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText("실제 쓰기 가능 여부: 미검증", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `../../docs/development/assets/P5-CODEX-104-controls-${info.project.name}.png`, fullPage: true });
});

test("automatic LIVE requires separate confirmation and preserves emergency", async ({ page }) => {
  await page.goto("/operations/automation");
  await page.getByLabel("변경 사유", { exact: true }).fill("격리 환경에서 자동 공개 확인 절차 검증");
  await page.getByRole("combobox", { name: "자동 발행 방식", exact: true }).selectOption("publish");
  await page.getByRole("checkbox", { name: "English Blogger · en" }).check();
  await page.getByRole("switch", { name: "Blogger 자동 발행" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "확인 후 적용" })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await expect(dialog.getByRole("button", { name: "확인 후 적용" })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: "LIVE 자동 공개를 별도로 승인합니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("switch", { name: "Blogger 자동 발행" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("switch", { name: "Blogger 긴급 정지" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByText("적용 상태: 긴급 정지로 차단").first()).toBeVisible();
});

test("emergency release needs confirmation and auto stays OFF", async ({ page }) => {
  await page.goto("/operations/automation");
  await page.getByLabel("변경 사유", { exact: true }).fill("격리 환경에서 긴급 정지 분리 해제 확인");
  await page.getByRole("switch", { name: "Blogger 긴급 정지" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("자동 발행 설정은 현재 OFF입니다.", { exact: false })).toBeVisible();
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("switch", { name: "Blogger 긴급 정지" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("switch", { name: "Blogger 긴급 정지" }).click();
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(page.getByRole("switch", { name: "Blogger 긴급 정지" })).toHaveAttribute("aria-checked", "false");
  await expect(page.getByRole("switch", { name: "Blogger 자동 발행" })).toHaveAttribute("aria-checked", "false");
});

test("unavailable settings stay visibly unavailable", async ({ page }) => {
  await page.route("**/api/automation-controls", route => route.fulfill({ status: 503, json: { error: "격리 API 연결 실패" } }));
  await page.goto("/operations/automation");
  await expect(page.getByRole("alert").filter({hasText:"격리 API 연결 실패"})).toBeVisible();
  await expect(page.getByRole("switch")).toHaveCount(0);
});


test("P104 route enable is confirmed and saved independently while master stays OFF", async ({ page }, info) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/operations/automation");
  await page.getByLabel("변경 사유", { exact: true }).fill("격리된 경로별 자동 발행 독립 저장 확인");
  const trends=page.getByRole("switch", {name:"Google Trends 원고 자동 발행",exact:true});
  const scheduled=page.getByRole("switch", {name:"일일 예약 원고 자동 발행",exact:true});
  await trends.click();
  const dialog=page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button",{name:"확인 후 적용"})).toBeDisabled();
  await dialog.getByRole("button",{name:"취소"}).click();
  await expect(trends).toHaveAttribute("aria-checked","false");
  await trends.click();await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button",{name:"확인 후 적용"}).click();
  await expect(trends).toHaveAttribute("aria-checked","true");
  await expect(page.getByRole("switch",{name:"Blogger 자동 발행",exact:true})).toHaveAttribute("aria-checked","false");
  await expect(scheduled).toHaveAttribute("aria-checked","false");
  await expect(page.getByRole("region",{name:"Google Trends 원고 자동 발행",exact:true}).getByText("적용 상태: 전체 자동 발행 OFF로 차단 중")).toBeVisible();
  await scheduled.click();await dialog.getByRole("checkbox").check();await dialog.getByRole("button",{name:"확인 후 적용"}).click();
  await expect(scheduled).toHaveAttribute("aria-checked","true");
  await trends.click();await expect(trends).toHaveAttribute("aria-checked","false");
  await expect(scheduled).toHaveAttribute("aria-checked","true");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({path:`../../docs/development/assets/P5-CODEX-104-paths-${info.project.name}.png`,fullPage:true});
});
