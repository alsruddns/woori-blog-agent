import { expect, test } from "playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

function envelope() {
  const tag = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const evidence = "The Official Agency published a policy notice describing a change to reporting requirements. The notice states that the policy is planned to take effect on 2026-11-01. The agency says organizations can use its reporting schedule to prepare for the stated date.";
  return {
    schema_version: "1.0", content_id: `e2e-import-${tag}`, event_group_id: `e2e-event-${tag}`,
    research_package_id: null, parent_content_id: null, relation: "original", source_region: "US", language_code: "en",
    target_audiences: [{ language_code: "en", target_region: "US", reader_relevance_reason: "The official policy notice directly affects organizations and readers in the United States." }],
    title: "Official Agency policy change and reporting schedule",
    body_markdown: "## What the notice says\n\nThe Official Agency notice describes a policy change to reporting requirements and states the planned effective date as 2026-11-01. [source:source-e2e]\n\n## Why the schedule matters\n\nOrganizations can use the agency reporting schedule to prepare for the stated date, while checking the published notice for the exact requirements. [source:source-e2e]\n\n## What readers should follow\n\nThe Official Agency notice is the reference for any later implementation details, so readers should compare updates with the published schedule. [source:source-e2e]",
    category: "policy", google_trends_based: false, source_ids: ["source-e2e"],
    sources: [{ source_id: "source-e2e", title: "Official Agency reporting notice", organization: "Official Agency", url: "https://example.gov/policy", published_at: "2026-10-20T10:00:00Z", observed_at: "2026-10-28T02:00:00Z", language_code: "en", source_type: "government", rights_status: "public_domain", rights_note: "Official material is listed as public domain; a human reviewer must confirm the applicable terms." }],
    claims: [{ claim_id: "claim-effective-date", claim: "The policy is planned to take effect on 2026-11-01.", source_ids: ["source-e2e"], evidence_excerpt: evidence, verification_status: "unverified", factual_state: "planned" }],
    fact_checked_at: "2026-10-28T02:00:00Z", seo: { search_intent: "Understand the reporting policy change", primary_terms: ["reporting policy"], related_terms: ["effective date"], seo_title: "Official Agency policy change and reporting schedule", search_description: "What the Official Agency notice says about the planned reporting policy change, its effective date, and how organizations can follow the published schedule.", core_question: "What does the reporting policy notice say?", core_answer: "It describes a reporting requirement change and gives a planned effective date." },
    blogger_labels: [], generation_method: "manual_codex_import", model_name: "Playwright import fixture", generated_at: "2026-10-28T02:00:00Z", created_by: "E2E Editorial Desk",
  };
}

test("isolated import flows through review, deterministic checks, preview, and fake publisher", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  const expectedSandboxBlocks: string[] = [];
  const expectedValidationResponses: string[] = [];
  const externalRequests: string[] = [];
  page.on("console", message => {
    if (message.type() !== "error") return;
    if (message.text().includes("Blocked script execution in 'about:srcdoc' because the document's frame is sandboxed")) expectedSandboxBlocks.push(message.text());
    else if (message.text().includes("Failed to load resource: the server responded with a status of 422")) expectedValidationResponses.push(message.text());
    else consoleErrors.push(message.text());
  });
  page.on("request", request => { if (!/^https?:\/\/(127\.0\.0\.1|localhost):(?:13100|18100)\//.test(request.url())) externalRequests.push(request.url()); });
  await page.goto("/imports");
  await expect(page.getByRole("heading", { name: "원고 Import 및 검토" })).toBeVisible();

  await page.getByLabel("제출자 표시 이름").fill("E2E Editorial Desk");
  await page.getByTestId("import-json").fill(JSON.stringify({ schema_version: "1.0" }));
  await page.getByRole("button", { name: "검토 대기열에 Import" }).click();
  await expect(page.getByRole("alert")).toBeVisible();

  const content = envelope();
  await page.getByLabel("JSON 파일 가져오기").setInputFiles({
    name: "content-import.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ submitted_by: "E2E Editorial Desk", item: content })),
  });
  await expect(page.getByTestId("import-json")).toHaveValue(JSON.stringify({ submitted_by: "E2E Editorial Desk", item: content }));
  await page.getByRole("button", { name: "검토 대기열에 Import" }).click();
  await expect(page.getByTestId("import-detail")).toBeVisible();
  await expect(page.getByTestId("import-title-input")).toHaveValue(content.title);
  await expect(page.getByText("외부 제출 · 독립 검증 미완료")).toBeVisible();

  await page.getByTestId("import-json").fill(JSON.stringify(content));
  await page.getByRole("button", { name: "검토 대기열에 Import" }).click();
  await expect(page.getByText("같은 원고가 이미 Import되어 있습니다. 중복 버전이나 검토 기록은 추가하지 않았습니다.")).toBeVisible();

  await page.getByTestId("import-title-input").fill("Official Agency policy change and reporting calendar");
  await page.getByTestId("import-body-input").fill(`${content.body_markdown}\n\n## Follow-up\n\nReaders can check the same notice for updates to its implementation schedule. [source:source-e2e]`);
  await page.getByTestId("save-import-version").click();
  await expect(page.getByText(/버전 2/)).toBeVisible();
  await page.getByRole("button", { name: "품질·SEO·HTML 검사" }).click();
  await expect(page.getByText("결정론적 규칙 통과")).toBeVisible();
  await page.getByRole("button", { name: "게시용 미리보기" }).click();
  const frame = page.frameLocator("[data-testid='import-html-preview']");
  await expect(page.getByTestId("import-detail").getByRole("heading", { name: "Official Agency policy change and reporting calendar", level: 2 })).toBeVisible();
  await expect(frame.getByRole("heading", { name: "What the notice says", level: 2 })).toBeVisible();
  await expect(page.getByText(/official_source_status/)).toHaveCount(0);

  await page.getByText("원문 문서를 직접 확인했습니다").click();
  await page.getByText("주장과 근거를 대조했습니다").click();
  await page.getByText("저작권·인용 권리를 검토했습니다").click();
  await page.getByRole("button", { name: "편집 검토 통과 기록" }).click();
  await expect(page.getByText("편집 검토 통과", { exact: true }).first()).toBeVisible();
  await page.getByTestId("mock-publish").click();
  await expect(page.getByText(/테스트 어댑터 결과를 기록했습니다/)).toBeVisible();
  await expect(page.getByText(/모의 결과: succeeded/)).toBeVisible();
  await expect(page.getByText(/publish_ready=false/).last()).toBeVisible();

  await page.getByLabel("대상 언어").selectOption("ko");
  await page.getByRole("button", { name: "현지화 원고 요청" }).click();
  await expect(page.getByText(/외부 공급자 대기로 저장/)).toBeVisible();
  await page.getByRole("button", { name: "요청 취소" }).click();
  await expect(page.getByText("한국어 · 요청 취소")).toBeVisible();
  await expect(page.getByText(/generation_provider_available.*true/)).toHaveCount(0);

  const screenshotDir = path.resolve(__dirname, "../../../docs/development/assets");
  mkdirSync(screenshotDir, { recursive: true });
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByTestId("import-detail")).toBeVisible();
    const overflow = await page.evaluate(() => ({
      page: document.documentElement.scrollWidth > window.innerWidth,
      offenders: [...document.querySelectorAll("body *")].map(element => {
        const rect = element.getBoundingClientRect();
        return { tag: element.tagName, className: typeof element.className === "string" ? element.className : "", right: Math.round(rect.right), scrollWidth: element.scrollWidth, clientWidth: element.clientWidth };
      }).filter(element => element.right > window.innerWidth + 1).slice(0, 8),
    }));
    expect(overflow.page, `document overflow at ${width}px: ${JSON.stringify(overflow.offenders)}`).toBe(false);
    await page.screenshot({ path: path.join(screenshotDir, `P5-CODEX-008-import-${testInfo.project.name}-${width}.png`), fullPage: true });
  }
  expect(externalRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(expectedValidationResponses.length).toBeGreaterThan(0);
  expect(expectedSandboxBlocks.length).toBeGreaterThan(0);
});
