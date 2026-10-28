import { expect, test } from "playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const importPath = path.resolve(__dirname, "../../../docs/development/P5-CODEX-009-content-import.json");
const envelope = JSON.parse(readFileSync(importPath, "utf8")) as Record<string, unknown>;
const item = envelope.item as Record<string, unknown>;

test("real Korean macro article imports, is assessed and previewed, and stays blocked pending human review", async ({ page }, testInfo) => {
  const externalRequests: string[] = [];
  const unexpectedConsoleErrors: string[] = [];
  page.on("request", request => {
    if (!/^https?:\/\/(127\.0\.0\.1|localhost):(?:13100|18100)\//.test(request.url())) externalRequests.push(request.url());
  });
  page.on("console", message => {
    if (message.type() === "error" && !message.text().includes("Blocked script execution in 'about:srcdoc'")) {
      unexpectedConsoleErrors.push(message.text());
    }
  });

  await page.goto("/imports");
  await expect(page.getByRole("heading", { name: "원고 Import 및 검토" })).toBeVisible();
  await page.getByLabel("제출자 표시 이름").fill("P5-CODEX-009 editorial evaluation");
  await page.getByLabel("JSON 파일 가져오기").setInputFiles({
    name: "P5-CODEX-009-content-import.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(envelope)),
  });
  await page.getByRole("button", { name: "검토 대기열에 Import" }).click();

  await expect(page.getByText(/원고를 검토 대기열에 저장했습니다|같은 원고가 이미 Import되어 있습니다/)).toBeVisible();
  const exactRow = page.locator(`[data-testid="import-row"][data-content-id="${String(item.content_id)}"]`);
  await expect(exactRow).toHaveCount(1);
  await exactRow.getByRole("button", { name: String(item.title), exact: true }).click();
  await expect(page.getByTestId("import-detail")).toBeVisible();
  await expect(page.getByTestId("import-detail")).toHaveAttribute("data-content-id", String(item.content_id));
  await expect(page.getByTestId("import-title-input")).toHaveValue(String(item.title));
  await expect(page.getByText("근거 상태: 외부 제출 · 독립 검증 미완료")).toBeVisible();
  await expect(page.getByText("이용권한: unknown", { exact: false })).toHaveCount(4);

  await page.getByRole("button", { name: "품질·SEO·HTML 검사" }).click();
  await expect(page.getByRole("heading", { name: "품질 검사 상세" })).toBeVisible();
  await expect(page.getByText(/결정론적 규칙 통과|기계 검사 보류/)).toBeVisible();
  await page.getByRole("button", { name: "게시용 미리보기" }).click();
  const frame = page.frameLocator("[data-testid='import-html-preview']");
  await expect(frame.locator("h1")).toHaveText("미국 소비는 버티는데, 체감경기는 왜 갈라지나");
  await expect(frame.locator("h1")).toHaveCount(1);
  await expect(frame.locator("body")).toContainText("지출액 증가와 실제 구매량은 다르다");
  await expect(frame.locator("body")).toContainText("7,450억 달러");
  await expect(frame.locator("body")).not.toContainText("[source:");
  await expect(page.getByText(/핵심 표현이 본문에 \d+회 있습니다/)).toBeVisible();
  await expect(page.getByText(/실제 Blogger 테마 적용 결과와 다를 수 있습니다/)).toBeVisible();
  await expect(page.getByTestId("mock-publish")).toBeDisabled();
  await expect(page.getByText(/publish_ready=false/).last()).toBeVisible();

  const localizationLanguage = testInfo.project.name === "desktop" ? "ja" : "zh-CN";
  const localizationName = localizationLanguage === "ja" ? "일본어" : "중국어 간체";
  await page.getByLabel("대상 언어").selectOption(localizationLanguage);
  await page.getByRole("button", { name: "현지화 원고 요청" }).click();
  await expect(page.getByText("다국어 원고 요청을 외부 공급자 대기로 저장했습니다.")).toBeVisible();
  await page.getByRole("button", { name: "요청 취소" }).click();
  await expect(page.getByText(`${localizationName} · 요청 취소`)).toBeVisible();

  const screenshotDir = path.resolve(__dirname, "../../../docs/development/assets");
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 980 });
    const overflow = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth > window.innerWidth,
      body: document.body.scrollWidth > window.innerWidth,
    }));
    expect(overflow, `layout overflow at ${width}px`).toEqual({ document: false, body: false });
    await page.screenshot({ path: path.join(screenshotDir, `P5-CODEX-009-real-article-${testInfo.project.name}-${width}.png`), fullPage: true });
  }
  expect(externalRequests).toEqual([]);
  expect(unexpectedConsoleErrors).toEqual([]);
});
