import { expect, test } from "playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const screenshots = path.resolve(__dirname, "../../../docs/development/assets");

test("manuscript list, filters, paged query, detail tabs and keyboard close", async ({ page }, testInfo) => {
  const listResponsePromise = page.waitForResponse(response =>
    response.url().includes("/api/research/manuscripts?") && response.status() === 200,
  );
  await page.goto("/manuscripts");
  const listResponse = await listResponsePromise;
  const list = await listResponse.json() as { total: number; items: Record<string, unknown>[] };
  expect(list.total).toBe(18);
  expect(list.items.length).toBeLessThanOrEqual(25);
  expect(list.items[0]).not.toHaveProperty("body");
  expect(list.items[0]).not.toHaveProperty("checks");
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByRole("row")).toHaveCount(list.items.length + 1);

  if (testInfo.project.name === "desktop") {
    await mkdir(screenshots, { recursive: true });
    await page.screenshot({ path: path.join(screenshots, "P5-UI-002-manuscripts-desktop.png"), fullPage: true });
  }

  await page.getByLabel(/언어/).selectOption("ko");
  await expect.poll(async () => (await page.getByRole("row").count()) - 1).toBeGreaterThan(0);
  await expect(page.getByLabel(/언어/)).toHaveValue("ko");
  const resetListResponsePromise = page.waitForResponse(response =>
    response.url().includes("/api/research/manuscripts?") && response.url().includes("page_size=25") && response.status() === 200,
  );
  await page.getByLabel(/언어/).selectOption("");
  const resetList = await (await resetListResponsePromise).json() as { items: Record<string, unknown>[] };

  await page.getByLabel(/페이지당 표시/).selectOption("10");
  await expect(page.getByRole("navigation").getByText("1 / 2 페이지")).toBeVisible();
  await page.getByRole("navigation").getByRole("button", { name: "다음" }).click();
  await expect(page.getByRole("navigation").getByText("2 / 2 페이지")).toBeVisible();
  await expect(page.getByRole("row")).toHaveCount(9);
  await page.getByLabel(/페이지당 표시/).selectOption("25");
  await expect(page.getByRole("navigation").getByText("1 / 1 페이지")).toBeVisible();

  const legacyIndex = resetList.items.findIndex(item => String(item.topic_key ?? "").startsWith("phase4l:"));
  expect(legacyIndex).toBeGreaterThanOrEqual(0);
  await expect(page.locator("tbody tr").nth(legacyIndex)).toContainText(String(resetList.items[legacyIndex].title));
  const firstDataRow = page.getByRole("row").nth(legacyIndex + 1);
  const detailResponsePromise = page.waitForResponse(response =>
    /\/api\/research\/manuscripts\/[0-9a-f-]+\/[0-9a-f-]+$/.test(new URL(response.url()).pathname) && response.status() === 200,
  );
  await firstDataRow.click();
  const detailPayload = await (await detailResponsePromise).json() as Record<string, unknown>;
  expect(detailPayload.topic_key).toBe(resetList.items[legacyIndex].topic_key);
  expect(detailPayload.review_actions_allowed).toBe(false);
  expect(detailPayload.publish_ready).toBe(false);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("iframe.article-preview")).toBeVisible();
  const previewText = await dialog.locator("iframe.article-preview").contentFrame().locator("body").innerText();
  expect(previewText.length).toBeGreaterThan(100);
  await expect(dialog.getByRole("tab")).toHaveCount(4);
  if (testInfo.project.name === "mobile") {
    await expect.poll(async () => await dialog.evaluate(el => Math.round(el.getBoundingClientRect().width))).toBeGreaterThanOrEqual(380);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await mkdir(screenshots, { recursive: true });
    await page.screenshot({ path: path.join(screenshots, "P5-UI-002-manuscripts-mobile.png"), fullPage: true });
  } else {
    await mkdir(screenshots, { recursive: true });
    await page.screenshot({ path: path.join(screenshots, "P5-UI-002-manuscript-detail-desktop.png"), fullPage: true });
  }
  await dialog.getByRole("tab", { name: /출처/ }).click();
  await expect(dialog.getByRole("tabpanel")).toBeVisible();
  await dialog.getByRole("tab", { name: /품질/ }).click();
  await expect(dialog.getByRole("tabpanel")).toBeVisible();
  await dialog.getByRole("tab", { name: /변경 이력/ }).click();
  await expect(dialog.getByRole("tabpanel")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(firstDataRow).toBeFocused();
});

test("trend observations render from the isolated six-region database", async ({ page }, testInfo) => {
  const responsePromise = page.waitForResponse(response =>
    response.url().includes("/api/research/trend-observations?") && response.status() === 200,
  );
  await page.goto("/sources");
  const response = await responsePromise;
  const payload = await response.json() as { total: number; items: Record<string, unknown>[] };
  expect(payload.total).toBe(60);
  expect(new Set(payload.items.map(row => row.geo)).size).toBeGreaterThan(1);
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByLabel(/국가/).selectOption("JP");
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(11);
  await page.getByLabel(/국가/).selectOption("");
  const firstRow = page.getByRole("row").nth(1);
  await firstRow.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("link").first()).toHaveAttribute("href", /^https:\/\//);
  await mkdir(screenshots, { recursive: true });
  await page.screenshot({
    path: path.join(screenshots, `P5-UI-002-source-detail-${testInfo.project.name}.png`),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  if (testInfo.project.name === "desktop") {
    await mkdir(screenshots, { recursive: true });
    await page.goto("/sources");
    await expect(page.getByRole("table")).toBeVisible();
    await page.screenshot({ path: path.join(screenshots, "P5-UI-002-sources-desktop.png"), fullPage: true });
  }
});

test("comparison and operations workspaces render at desktop and mobile sizes", async ({ page }, testInfo) => {
  await mkdir(screenshots, { recursive: true });
  const comparison = await page.goto("/model-comparison");
  expect(comparison?.status()).toBe(200);
  await expect(page.locator("h1")).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, `P5-UI-002-model-comparison-${testInfo.project.name}.png`),
    fullPage: true,
  });

  const operations = await page.goto("/operations");
  expect(operations?.status()).toBe(200);
  await expect(page.locator("h1")).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, `P5-UI-002-operations-${testInfo.project.name}.png`),
    fullPage: true,
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("model comparison and compatibility routes use stored data", async ({ page }) => {
  const comparePromise = page.waitForResponse(response =>
    response.url().includes("/api/research/model-comparisons?") && response.status() === 200,
  );
  await page.goto("/model-comparison");
  const compare = await (await comparePromise).json() as { total: number };
  expect(compare.total).toBe(36);
  await expect(page.getByText(/36/)).toBeVisible();

  const operations = await page.goto("/operations");
  expect(operations?.status()).toBe(200);
  const research = await page.goto("/research");
  expect(research?.status()).toBe(200);
  await expect(page).toHaveURL(/\/manuscripts$/);
  await expect(page.getByRole("heading", { name: /작성 원고/ })).toBeVisible();
});

test("list request failure is shown as an accessible page error", async ({ page }) => {
  await page.route("**/api/research/manuscripts?**", route => route.abort());
  await page.goto("/manuscripts");
  await expect(page.locator("p.error-state[role='alert']")).toContainText("원고 목록을 불러오지 못했습니다");
});

test("Blogger article preview keeps one title and fits narrow mobile widths", async ({ page }, testInfo) => {
  const evaluationId = "11111111-1111-4111-8111-111111111111";
  const contentVersionId = "22222222-2222-4222-8222-222222222222";
  const externalRequests: string[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (!["127.0.0.1", "localhost"].includes(url.hostname)) externalRequests.push(url.origin);
  });
  await page.route("**/api/research/manuscripts?**", route => route.fulfill({ json: {
    items: [{ evaluation_id: evaluationId, content_version_id: contentVersionId, title: "Sample policy article", topic: "Sample policy article", category_slug: "finance", language_code: "ko", model: "Qwen3", created_at: "2026-10-28T00:00:00Z", editorial_status: "quality_held", machine_passed: false, publication_status: "draft" }],
    page: 1, page_size: 25, total: 1, languages: ["ko"], categories: ["finance"],
  } }));
  await page.route(`**/api/research/manuscripts/${evaluationId}/${contentVersionId}`, route => route.fulfill({ json: {
    id: evaluationId, evaluation_id: evaluationId, content_version_id: contentVersionId, topic_key: "phase39t:test", title: "Sample policy article", saved_title: "Sample policy article", saved_body: "# Sample policy article\n\n## Key question\n\nA verified paragraph with enough context.", body: "", body_format: "markdown", language_code: "ko", model: "Qwen3", created_at: "2026-10-28T00:00:00Z", summary: "Search description only.", sources: [{ id: "source-1", source_name: "Official source", url: "https://example.gov/source" }], facts: [], checks: {}, machine_passed: false, editorial_status: "quality_held", editorial_versions: [], review_history: [], review_events: [], publication_approval_events: [], blogger_targets: [{ id: "33333333-3333-4333-8333-333333333333", language_code: "ko", url: "https://trend-ko.blogspot.com", display_name: "Trend Korea", blog_id: "1234567890", active: true, connection_verified_at: "2026-10-27T00:00:00Z" }], review_actions_allowed: false, publish_ready: false,
  } }));
  await page.route("**/api/research/editorial-preview", async route => {
    const request = route.request().postDataJSON() as { google_trends_based: boolean; target_blog_record_id?: string | null };
    await route.fulfill({ json: {
      title: "Sample policy article", language_code: "ko", post_html: '<article class="wb-article"><h2>Key question</h2><p>A verified paragraph with enough context.</p><figure><img src="https://images.example.test/chart.png" alt="Budget chart"><figcaption>Chart caption</figcaption></figure><div class="wb-table-wrap"><table><tr><td>320px content</td></tr></table></div></article>',
      labels: request.google_trends_based ? ["이슈"] : [], title_in_body: false, publication_performed: false,
      renderer_version: "1.1.0", design_system_version: "1.1.0", rendered_sha256: "a".repeat(64),
      seo_metadata: { language_code: "ko", target_region: null, search_intent: null, seo_title: "Sample policy article", search_description: "Search description only.", primary_keyword: "policy", related_terms: [], core_question: null, core_answer: null, category: "finance", blogger_labels: [], official_sources: [{ title: "Official source", url: "https://example.gov/source", official_status: "unverified" }], fact_verified_at: null, editorial_status: "quality_held" },
      seo_checks: [{ key: "title_matches_article", status: "ready", message: "검색 제목이 실제 게시 제목과 같습니다." }, { key: "search_performance", status: "not_measured", message: "Search Console 미연결" }],
      publication_package: { package_version: "1.0.0", package_sha256: "c".repeat(64), generated_at: "2026-10-28T00:00:00Z", target_blog: request.target_blog_record_id ? { blog_record_id: request.target_blog_record_id, blog_id: "1234567890", url: "https://trend-ko.blogspot.com" } : null, request: { method: "posts.insert", query: { isDraft: true }, body: { title: "Sample policy article", content: "<p>Safe content</p>", labels: ["이슈"] } }, editorial_version: { content_version_id: contentVersionId, editorial_revision_id: null, revision_number: null, body_sha256: "d".repeat(64), rendered_sha256: "a".repeat(64) }, seo: { title: "Sample policy article", title_candidates: ["Sample policy article title"], search_description: "Search description only.", search_description_api_supported: false }, sources: [{ title: "Official source", url: "https://example.gov/source", official_status: "unverified" }], theme_compatibility: { status: "live_theme_not_inspected" }, renderer_version: "1.1.0", design_system_version: "1.1.0", validation: [], editorial_approval: "not_evaluated_by_package_builder", publish_ready: false, submission_performed: false, blockers: request.target_blog_record_id ? ["live_blogger_access_not_rechecked"] : ["target_blog_not_selected_or_registered"] },
      search_console: { source: "google_search_console", measured_at: null, impressions: null, clicks: null, ctr: null, average_position: null, queries: [], country: null, index_status: null },
    } });
  });

  await page.goto("/manuscripts");
  await page.getByRole("row", { name: /Sample policy article/ }).click();
  const frame = page.locator("iframe").contentFrame();
  await expect(frame.getByRole("heading", { name: "Sample policy article", level: 1 })).toHaveCount(1);
  await expect(frame.locator("article h1")).toHaveCount(0);
  await expect(frame.getByRole("img", { name: /Budget chart/ })).toBeVisible();
  await expect(frame.locator('link[href="/blogger-editorial.css"]')).toHaveCount(1);
  await expect(frame.locator(".wb-post-title")).toHaveCSS("font-size", /\d+px/);
  await page.getByText("원고와 출처 보기").click();
  await expect(page.getByText("Official source")).toBeVisible();
  await page.getByLabel("Google Trends 기반 원고").check();
  await expect(page.getByText("이슈", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "SEO 점검" }).click();
  await expect(page.getByLabel("게시 전 SEO 점검")).toContainText("Search Console 연결 없음");
  await expect(page.getByLabel("게시 전 SEO 점검")).toContainText("공식성 확인 필요");
  await page.getByLabel("대상 블로그 (등록 정보만 조회)").selectOption("33333333-3333-4333-8333-333333333333");
  await page.getByRole("button", { name: "발행 준비 자료" }).click();
  await expect(page.getByLabel("Blogger 발행 준비 자료")).toContainText("미전송");
  await expect(page.getByLabel("Blogger 발행 준비 자료")).toContainText("trend-ko.blogspot.com");
  await expect(page.getByLabel("Blogger 발행 준비 자료")).toContainText("publish_ready=false");
  await expect(page.getByLabel("Blogger 발행 준비 자료")).toContainText("현재 Blogger 접근 권한은 실조회하지 않았습니다.");
  await expect(page.getByLabel("Blogger 발행 준비 자료")).toContainText("Sample policy article title");
  await expect(page.getByLabel("Blogger 발행 준비 자료")).toContainText("Official source");
  await mkdir(screenshots, { recursive: true });
  await page.screenshot({ path: path.join(screenshots, `P5-CODEX-005-package-${testInfo.project.name}.png`), fullPage: true });
  const [packageDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "준비 자료 JSON 저장" }).click(),
  ]);
  expect(packageDownload.suggestedFilename()).toMatch(/^woori-publication-preparation-/);
  await page.getByRole("button", { name: "화면 미리보기" }).click();

  for (const width of [320, 390, 430, 768, 1280, 1920]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await frame.locator("html").evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(frame.locator(".wb-preview-shell")).toHaveCSS("color", "rgb(227, 235, 230)");
  await page.emulateMedia({ colorScheme: "light" });
  expect(externalRequests).toEqual([]);
  await mkdir(screenshots, { recursive: true });
  await page.setViewportSize({ width: 320, height: 844 });
  await page.screenshot({ path: path.join(screenshots, "P5-CODEX-004-preview-320.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({ path: path.join(screenshots, "P5-CODEX-004-preview-desktop.png"), fullPage: true });
});

test("shared article CSS tolerates representative Blogger theme baselines in all supported locales", async ({ page }) => {
  const externalRequests: string[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (!(["127.0.0.1", "localhost"].includes(url.hostname))) externalRequests.push(url.origin);
  });
  await page.goto("/manuscripts");
  const fixtures = [
    { lang: "ko", heading: "정책 변화와 독자가 알아야 할 점", body: "검증된 한국어 문단입니다.", wrapper: "post-body", theme: ".post-body h2{font-size:10px;color:purple}.post-body img{max-width:280px}" },
    { lang: "en", heading: "What the policy change means", body: "This verified English paragraph remains readable.", wrapper: "entry-content", theme: ".entry-content h2{font-size:10px;color:navy}.entry-content table{min-width:1100px}" },
    { lang: "ja", heading: "政策変更が意味すること", body: "確認された日本語の本文です。", wrapper: "blog-post post-body", theme: ".blog-post h2{font-size:10px;color:teal}.blog-post img{height:auto}" },
    { lang: "zh-CN", heading: "政策变化意味着什么", body: "这是经过核实的简体中文段落。", wrapper: "post-body entry-content", theme: "h2{font-size:10px;color:maroon}.post-body a{word-break:normal}" },
  ];
  for (const fixture of fixtures) {
    await page.setContent(`<!doctype html><html lang="${fixture.lang}"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:12px/1.2 serif}${fixture.theme}</style><link rel="stylesheet" href="/blogger-editorial.css"></head><body><main class="${fixture.wrapper}"><article class="wb-article"><h2>${fixture.heading}</h2><p>${fixture.body}</p><p><a href="https://example.gov/this-is-a-long-source-url-that-needs-wrapping">https://example.gov/this-is-a-long-source-url-that-needs-wrapping</a></p><div class="wb-table-wrap"><table><thead><tr><th>項目</th><th>Very long numeric value 12345678901234567890</th></tr></thead><tbody><tr><td>資料</td><td>NT$6,076 億</td></tr></tbody></table></div><figure><img src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt="자료 비교 도표"><figcaption>자료 설명</figcaption></figure><div class="wb-stat-grid"><div class="wb-stat-card">항목 1</div><div class="wb-stat-card">項目 2</div></div></article></main></body></html>`);
    const h2Size = Number.parseFloat(await page.locator(".wb-article h2").evaluate(element => getComputedStyle(element).fontSize));
    expect(h2Size).toBeGreaterThanOrEqual(23);
    expect(h2Size).toBeLessThanOrEqual(25);
    await expect(page.locator(".wb-article")).toContainText(fixture.body);
    for (const width of [320, 390, 768, 1280, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
  }
  expect(externalRequests).toEqual([]);
});
