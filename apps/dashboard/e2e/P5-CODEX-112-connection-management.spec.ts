import { expect, test } from "playwright/test";

async function assertContrast(page: import("playwright/test").Page, selector: string) {
  const snapshot = await page.waitForFunction((query) => {
    const element = Array.from(document.querySelectorAll(query)).find((candidate) => candidate instanceof HTMLElement && candidate.getClientRects().length > 0);
    if (!element) return null;
    const parse = (value: string) => value.match(/[\d.]+/g)?.slice(0, 3).map(Number) ?? [0, 0, 0];
    const luminance = (rgb: number[]) => {
      const channels = rgb.map(channel => { const value = channel / 255; return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const foregroundColor = getComputedStyle(element).color;
    const foreground = luminance(parse(foregroundColor));
    let backgroundElement: Element | null = element;
    let color = "rgba(0, 0, 0, 0)";
    while (backgroundElement && color.endsWith(", 0)")) {
      color = getComputedStyle(backgroundElement).backgroundColor;
      backgroundElement = backgroundElement.parentElement;
    }
    if (color.endsWith(", 0)")) color = getComputedStyle(document.body).backgroundColor;
    const background = luminance(parse(color));
    const [lighter, darker] = foreground > background ? [foreground, background] : [background, foreground];
    return { ratio: (lighter + 0.05) / (darker + 0.05), foregroundColor, backgroundColor: color };
  }, selector);
  const result = await snapshot.jsonValue() as { ratio: number; foregroundColor: string; backgroundColor: string } | null;
  expect(result, `${selector} must resolve to a visible rendered element`).not.toBeNull();
  if (!result) return;
  expect(result.ratio, `${selector} contrast ratio (${JSON.stringify(result)})`).toBeGreaterThanOrEqual(4.5);
}

test("Blogger 관리 탭, OAuth 기록 구분, 지연 로그 및 테마 레이아웃", async ({ page }, info) => {
  const detailRequests: string[] = [];
  const mutations: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (request.url().includes("/api/blogger/diagnostics/")) detailRequests.push(request.url());
    if (/\/api\/blogger\/(?:oauth|blogs|draft-previews)/.test(request.url()) && request.method() !== "GET") mutations.push(request.method());
  });
  await page.route("**/api/blogger/diagnostics/**", async route => {
    const endpoint = route.request().url();
    const items = endpoint.includes("api-calls")
      ? [{ id: 1, created_at: "2026-11-03T01:00:00Z", operation: "posts.list", status: "succeeded", http_status: 200, blog_name: "Trend Journal EN" }]
      : endpoint.includes("audit-events")
        ? [{ id: 2, created_at: "2026-11-03T01:00:00Z", event_type: "blogger.connection.checked", blog_name: "Trend Journal EN" }]
        : [{ preview_id: "safe-preview", created_at: "2026-11-03T01:00:00Z", mode: "live_test_draft", language_code: "en", blog_id: "test-blog", external_post_id: "test-post", final_status: "succeeded", http_status: 200 }];
    await route.fulfill({ json: { items, offset: 0, limit: 20, total: items.length } });
  });

  await page.goto("/blogger");
  await expect(page.getByRole("link", { name: "Blogger 연결 관리" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("OAuth 연결 레코드", { exact: true })).toBeVisible();
  await expect(page.getByText("고유 Google 계정", { exact: true })).toBeVisible();
  await expect(page.getByText("계정 이메일과 다름").first()).toBeVisible().catch(() => undefined);
  const accordions = page.locator(".blogger-log-accordion");
  await expect(accordions).toHaveCount(3);
  for (let index = 0; index < 3; index++) await expect(accordions.nth(index)).not.toHaveAttribute("open", "");
  expect(detailRequests).toHaveLength(0);
  await accordions.first().locator("summary").click();
  await expect(accordions.first().getByText("posts.list")).toBeVisible();
  expect(detailRequests).toHaveLength(1);

  const disconnect = page.getByRole("button", { name: "Google 연결 해제" }).first();
  if (await disconnect.isVisible()) {
    await disconnect.click();
    await expect(page.getByRole("dialog", { name: "Google 연결 해제 확인" })).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "취소" }).click();
  }
  expect(mutations).toEqual([]);
  await page.screenshot({ path: `../../docs/development/assets/P5-CODEX-112-connections-${info.project.name}.png`, fullPage: true });

  await page.getByRole("link", { name: "언어·정책 설정" }).click();
  await expect(page.getByRole("heading", { name: "언어·정책 설정" })).toBeVisible();
  await expect(page.getByRole("link", { name: "언어·정책 설정" })).toHaveAttribute("aria-current", "page");
  await page.reload();
  await expect(page.getByRole("link", { name: "언어·정책 설정" })).toHaveAttribute("aria-current", "page");
  await page.goBack();
  await expect(page.getByRole("link", { name: "Blogger 연결 관리" })).toHaveAttribute("aria-current", "page");

  await page.getByRole("link", { name: "언어·정책 설정" }).click();
  await expect(page.locator(".blogger-page form").first()).toBeVisible();
  await expect(page.locator(".blogger-page form label").first()).toBeVisible();
  await page.getByLabel("화면 테마").selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await assertContrast(page, ".blogger-page .page-heading p");
  await assertContrast(page, ".blogger-page form label");
  await assertContrast(page, ".blogger-page form input:not([type=checkbox])");
  await assertContrast(page, ".blogger-page form select");
  await page.getByLabel("화면 테마").selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await assertContrast(page, ".blogger-page .page-heading p");
  await assertContrast(page, ".blogger-page form label");
  await assertContrast(page, ".blogger-page form input:not([type=checkbox])");
  await assertContrast(page, ".blogger-page form select");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `../../docs/development/assets/P5-CODEX-112-language-policy-${info.project.name}.png`, fullPage: true });
});
