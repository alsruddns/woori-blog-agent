import { expect, test } from "playwright/test";

test("all controls persist through the confirmation flow", async ({ page }, info) => {
  const settings = {
    revision: 9, updated_at: "2026-11-02T08:00:00Z",
    trends_collection_enabled: true, auto_manuscript_enabled: true,
    auto_publishing_enabled: false, trends_auto_publishing_enabled: false,
    scheduled_auto_publishing_enabled: false, manual_publishing_enabled: true,
    emergency_stop: false, blogger_api_restricted: false,
    interval_minutes: 30, global_publish_min_interval_minutes: 15, global_daily_live_publish_limit: 100, auto_mode: "draft", auto_blog_ids: [] as string[],
    google_account_report: "user_reported_available", read_check_result: {},
  };
  const requests: Record<string, unknown>[] = [];
  const blog = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa";
  await page.route("**/api/automation-controls**", async route => {
    const request = route.request();
    if (request.method() === "PUT") {
      const body = request.postDataJSON() as Record<string, unknown>;
      requests.push(body);
      if (body.expected_revision !== settings.revision) return route.fulfill({ status: 409, json: { detail: "설정이 변경되었습니다. 최신 상태를 다시 불러오세요." } });
      for (const key of Object.keys(settings) as (keyof typeof settings)[]) {
        if (key in body && key !== "revision") Object.assign(settings, { [key]: body[key] });
      }
      settings.revision++;
      return route.fulfill({ json: { saved: true, revision: settings.revision, application: "pending_worker_ack" } });
    }
    return route.fulfill({ json: {
      settings, effective: Object.fromEntries([
        "trends_collection_enabled", "auto_manuscript_enabled", "auto_publishing_enabled",
        "manual_publishing_enabled", "trends_auto_publishing_enabled", "scheduled_auto_publishing_enabled",
      ].map(key => [key, settings[key as keyof typeof settings] ? "정상" : "신규 실행 중지"])),
      workers: ["research_worker", "publication_worker"].map((service_name, i) => ({ service_name, process_id: i + 100, applied_revision: settings.revision, policy_applied: true, policy_seen_at: "2026-11-02T08:00:00Z" })),
      history: [], blogs: [{ id: blog, display_name: "English Blogger", language_code: "en" }],
      recent: { region_count: 11, last_collection: null, last_import: null, last_authoring: null, authoring_queued: 0, authoring_running: 0 },
      eligible_jobs: 0, last_publication: null,
    } });
  });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/operations/automation");
  const scheduled = page.getByRole("switch", { name: "일일 예약 원고 자동 발행" });
  await scheduled.click();
  await expect(page.getByRole("alert").filter({ hasText: "10자 이상" })).toBeVisible();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(requests).toHaveLength(0);
  await page.getByLabel("변경 사유", { exact: true }).fill("격리 화면에서 예약 원고 공개 설정 검증");
  await scheduled.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "확인 후 적용" })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(scheduled).toHaveAttribute("aria-checked", "true");
  expect(requests.at(-1)).toMatchObject({ scheduled_auto_publishing_enabled: true, confirm_auto: true, actor: "관리자" });
  await page.getByRole("combobox", { name: "자동 발행 방식" }).selectOption("publish");
  await page.getByRole("checkbox", { name: "English Blogger · en" }).check();
  await page.getByRole("button", { name: "발행 방식·대상 저장" }).click();
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await expect(dialog.getByRole("button", { name: "확인 후 적용" })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: "LIVE 자동 공개를 별도로 승인합니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  expect(requests.at(-1)).toMatchObject({ auto_mode: "publish", auto_blog_ids: [blog], confirm_live: true });
  await page.getByRole("switch", { name: "Blogger 자동 발행", exact: true }).click();
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await dialog.getByRole("checkbox", { name: "LIVE 자동 공개를 별도로 승인합니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(page.getByRole("switch", { name: "Blogger 자동 발행", exact: true })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("combobox", { name: "자동 발행 방식" }).selectOption("draft");
  await page.getByRole("button", { name: "발행 방식·대상 저장" }).click();
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(page.getByText("저장된 방식: Draft", { exact: false })).toBeVisible();
  await page.getByRole("combobox", { name: "자동 발행 방식" }).selectOption("publish");
  await page.getByRole("button", { name: "발행 방식·대상 저장" }).click();
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await dialog.getByRole("checkbox", { name: "LIVE 자동 공개를 별도로 승인합니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(page.getByText("저장된 방식: LIVE", { exact: false })).toBeVisible();
  for (const name of ["Google Trends 수집", "Codex 자동 원고 작성", "Blogger 수동 발행", "일일 예약 원고 자동 발행"]) {
    const control = page.getByRole("switch", { name, exact: true });
    await control.click();
    await expect(control).toHaveAttribute("aria-checked", "false");
    if (name !== "일일 예약 원고 자동 발행") {
      await control.click();
      await expect(control).toHaveAttribute("aria-checked", "true");
    }
  }
  await page.getByRole("switch", { name: "Google Trends 원고 자동 발행" }).click();
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await dialog.getByRole("checkbox", { name: "LIVE 자동 공개를 별도로 승인합니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await page.getByRole("switch", { name: "Google Trends 원고 자동 발행" }).click();
  await page.getByRole("switch", { name: "Blogger 긴급 정지" }).click();
  await expect(page.getByRole("switch", { name: "Blogger 긴급 정지" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("switch", { name: "Blogger 긴급 정지" }).click();
  await dialog.getByRole("checkbox", { name: "대상과 적용 범위를 확인했습니다." }).check();
  await dialog.getByRole("button", { name: "확인 후 적용" }).click();
  await expect(page.getByRole("switch", { name: "Blogger 긴급 정지" })).toHaveAttribute("aria-checked", "false");
  await page.reload();
  await expect(page.getByText(`저장된 설정 revision ${settings.revision}`, { exact: false })).toBeVisible();
  await expect(page.getByText(`적용 revision ${settings.revision}`, { exact: false }).first()).toBeVisible();
  expect(requests).toHaveLength(16);
  await page.getByRole("combobox", { name: "화면 테마" }).selectOption("dark");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `../../docs/development/assets/P5-CODEX-106-controls-${info.project.name}.png`, fullPage: true });
});

test("failed save keeps the previous switch value and offers a retry", async ({ page }) => {
  let writes = 0;
  await page.route("**/api/automation-controls", route => {
    if (route.request().method() === "PUT") {
      writes++;
      return route.fulfill({ status: 503, json: { error: "격리 DB 저장 장애" } });
    }
    return route.fulfill({ json: {
      settings: { revision: 4, trends_collection_enabled: true, auto_manuscript_enabled: true,
        auto_publishing_enabled: false, trends_auto_publishing_enabled: false,
        scheduled_auto_publishing_enabled: false, manual_publishing_enabled: true,
        emergency_stop: false, blogger_api_restricted: false, interval_minutes: 30,
        global_publish_min_interval_minutes: 15,
        global_daily_live_publish_limit: 100,
        auto_mode: "draft", auto_blog_ids: [], google_account_report: "unverified", read_check_result: {} },
      effective: {}, workers: [], history: [], blogs: [],
      recent: { region_count: 11, last_collection: null, last_import: null,
        last_authoring: null, authoring_queued: 0, authoring_running: 0 },
      eligible_jobs: 0, last_publication: null,
    } });
  });
  await page.goto("/operations/automation");
  await page.getByLabel("변경 사유", { exact: true }).fill("격리 데이터베이스 저장 장애 복구 검증");
  const control = page.getByRole("switch", { name: "Blogger 수동 발행" });
  await control.click();
  await expect(page.getByRole("status").filter({ hasText: "설정 변경 실패" })).toBeVisible();
  await expect(control).toHaveAttribute("aria-checked", "true");
  await control.click();
  expect(writes).toBe(2);
  await expect(control).toHaveAttribute("aria-checked", "true");
});
