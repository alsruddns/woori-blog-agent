import { expect, test } from "playwright/test";

test("operations shell keeps route state and responsive navigation across target widths", async ({ page }) => {
  const routes = [
    ["/", "대시보드", "콘텐츠 운영 현황"],
    ["/publishing", "발행 관리", "발행 관리"],
    ["/operations/research", "자동화 관리", "자동화 관리"],
    ["/blogger", "Blogger 연결", "Blogger 연결 관리"],
  ] as const;

  for (const [route, navLabel, heading] of routes) {
    await page.goto(route);
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
    const navigation = page.getByRole("navigation", { name: "주 메뉴" });
    await expect(navigation.getByRole("link", { name: navLabel })).toHaveAttribute("aria-current", "page");
    for (const width of [390, 768, 1280, 1920]) {
      await page.setViewportSize({ width, height: width < 500 ? 844 : 900 });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
  }
});

test("theme preference persists and mobile navigation supports Escape", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const theme = page.getByLabel("화면 테마");
  await theme.selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const darkBackground = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(darkBackground);
  await page.getByRole("button", { name: "메뉴 열기" }).click();
  await expect(page.locator("#dashboard-sidebar")).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Escape");
  await expect(page.locator("#dashboard-sidebar")).not.toHaveAttribute("aria-modal", "true");
  await page.getByLabel("화면 테마").selectOption("system");
});
