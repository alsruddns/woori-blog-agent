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
