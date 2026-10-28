import { expect, test } from "playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const screenshots = path.resolve(__dirname, "../../../docs/development/assets");
const importId = "ui003-import-fixture";

const importItem = {
  id: importId,
  external_content_id: "ui003-content-family",
  title: "Test policy analysis for editorial review",
  category: "policy",
  language_code: "en",
  source_region: "US",
  received_at: "2026-10-28T10:00:00Z",
  seo_metadata: {},
  blogger_labels: [],
  sources: [{ source_id: "ui003-source", title: "Official policy notice", organization: "Official Agency", url: "https://example.gov/notice", rights_status: "unknown_rights" }],
  claims: [{ claim_id: "ui003-claim", claim: "The policy is planned.", source_ids: ["ui003-source"], verification_status: "unverified", factual_state: "planned", evidence_excerpt: "The notice describes a planned change." }],
};

const importDetail = {
  item: importItem,
  latest_version: {
    id: "ui003-version-1",
    content_version_id: "ui003-content-family",
    version_number: 1,
    title: importItem.title,
    body_markdown: "## What changed\n\nThe public notice describes the proposed change and its stated date.",
    seo_metadata: {},
    blogger_labels: [],
    created_at: "2026-10-28T10:00:00Z",
    author_label: "Editorial review fixture",
    change_reason: "Browser navigation check",
    content_sha256: "fixture-hash",
  },
  versions: [],
  assessments: [],
  reviews: [],
  editorial_review_status: "awaiting_human_review",
  localization_requests: [],
  mock_publications: [],
  publish_ready: false,
  generation_ready: false,
};

test("manuscript navigation opens one-click import detail and remains responsive", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.route("**/api/research/content-imports**", async route => {
    const method = route.request().method();
    const url = new URL(route.request().url());
    if (method === "GET" && url.pathname.endsWith(`/content-imports/${importId}`)) {
      await route.fulfill({ json: importDetail });
    } else if (method === "GET") {
      await route.fulfill({ json: { items: [importItem], total: 1 } });
    } else {
      await route.fulfill({ status: 409, json: { detail: "This UI fixture does not permit writes." } });
    }
  });

  await page.goto("/manuscripts");
  await expect(page.getByRole("navigation", { name: "주 메뉴" })).toBeVisible();
  await expect(page.getByRole("link", { name: "원고 관리" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("18개 원고")).toBeVisible();
  await expect(page.getByRole("tab", { name: /외부 검토 대기/ })).toBeVisible();
  await page.getByRole("tab", { name: /외부 검토 대기/ }).click();
  await expect(page.getByRole("link", { name: importItem.title })).toBeVisible();
  await page.getByRole("link", { name: importItem.title }).click();
  await expect(page).toHaveURL(new RegExp(`/imports\\?open_import_id=${importId}`));
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: importItem.title })).toBeVisible();
  await expect(dialog.getByRole("tab", { name: "출처·근거" })).toBeVisible();
  await expect(dialog.getByRole("tab", { name: "품질·SEO" })).toBeVisible();
  await dialog.getByRole("tab", { name: "출처·근거" }).click();
  await expect(dialog.getByRole("tabpanel").getByRole("heading", { name: "출처와 주장" })).toBeVisible();
  await expect(dialog.getByRole("tabpanel")).toContainText("이용 권리 미확인");
  await expect(dialog.getByRole("tabpanel")).toContainText("사실 검증 미완료");
  await expect(dialog.getByRole("tabpanel")).toContainText("예정");
  await expect(dialog.getByRole("tabpanel")).toContainText("Official policy notice");
  await expect(dialog.getByRole("tabpanel")).not.toContainText("unverified");
  await expect(dialog.getByRole("tabpanel")).not.toContainText("ui003-source");
  await dialog.getByRole("tab", { name: "원고 편집" }).click();
  await expect(dialog.getByTestId("import-title-input")).toHaveValue(importItem.title);

  for (const width of [320, 390, 768, 1280, 1920]) {
    await page.setViewportSize({ width, height: width < 500 ? 844 : 1000 });
    await expect(dialog).toBeVisible();
    if (width <= 430) {
      const drawerHeight = await dialog.evaluate(element => element.getBoundingClientRect().height);
      expect(drawerHeight).toBeGreaterThanOrEqual(843);
    }
    const hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(hasOverflow, `unexpected document overflow at ${width}px`).toBe(false);
    if (width === 390 || width === 1280) {
      mkdirSync(screenshots, { recursive: true });
      await page.screenshot({ path: path.join(screenshots, `P5-UI-003-import-detail-${width}.png`) });
    }
  }

  await page.goBack();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/\/manuscripts\?.*view=external/);
  await expect(page.getByRole("link", { name: importItem.title })).toBeVisible();
  await page.getByRole("link", { name: importItem.title }).click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  expect(consoleErrors).toEqual([]);
});

test("publishing page uses Korean copy and explains unavailable server state", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.goto("/publishing");
  await expect(page.getByRole("heading", { name: "발행 관리" })).toBeVisible();
  await expect(page.locator("main p[role='alert']")).toContainText("서버가 발행 정보를 불러오지 못했습니다");
  await expect(page.getByRole("link", { name: "발행 관리" })).toHaveAttribute("aria-current", "page");
  const visibleText = await page.locator("main").innerText();
  expect(visibleText).not.toContain("Local API");
  expect(visibleText).not.toContain("Simulation only");
  for (const width of [320, 390, 768, 1280, 1920]) {
    await page.setViewportSize({ width, height: width < 500 ? 844 : 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `publishing page overflow at ${width}px`).toBe(true);
    if (width === 390 || width === 1280) {
      mkdirSync(screenshots, { recursive: true });
      await page.screenshot({ path: path.join(screenshots, `P5-UI-003-publishing-${width}.png`), fullPage: true });
    }
  }
  expect(consoleErrors).toEqual([]);
});

test("automation and diagnostics navigation reflect the current route without duplicate active items", async ({ page }) => {
  await page.goto("/operations/research#automation");
  const navigation = page.getByRole("navigation", { name: "주 메뉴" });
  await expect(navigation.getByRole("link", { name: "자동화 관리" })).toHaveAttribute("aria-current", "page");
  await expect(navigation.getByRole("link", { name: "운영 진단" })).not.toHaveAttribute("aria-current", "page");
  await page.goto("/operations");
  await expect(navigation.getByRole("link", { name: "운영 진단" })).toHaveAttribute("aria-current", "page");
  await expect(navigation.getByRole("link", { name: "자동화 관리" })).not.toHaveAttribute("aria-current", "page");
});
