import { expect, test } from "playwright/test";

test("manual-only status is visible on all operational screens without automatic writes", async ({page}) => {
  const writes: string[] = [];
  await page.route("**/api/**", async route => {
    if (route.request().method() !== "GET") { writes.push(route.request().url()); return route.abort(); }
    return route.continue();
  });
  for (const path of ["/sources", "/publishing", "/manuscripts"]) {
    await page.goto(path);
    await expect(page.getByTestId("authoring-only-notice")).toContainText("Blogger 자동 발행 OFF");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  expect(writes).toEqual([]);
});

test("manual defaults to publish, cancel performs no request, draft and publish submit only on click", async ({page}) => {
  const requests: Record<string, unknown>[] = [];
  await page.route("**/api/publications/manual-live-requests", async route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({status:201,json:{id:"00000000-0000-0000-0000-000000000097",recorded:true,followup_count:0}});
  });
  // Simulate a future, actually cleared restriction; production stays blocked.
  await page.route("**/api/publications/scheduled-auto-state?*", async route => {
    const response = await route.fetch({headers:{...route.request().headers(),origin:new URL(route.request().url()).origin}});
    const data = await response.json();
    for (const target of data.targets ?? []) {
      if (target.manual_publication) { target.manual_publication.eligible=true; target.manual_publication.blockers=[]; target.manual_publication.jobs=[]; }
    }
    return route.fulfill({json:data});
  });
  await page.goto("/imports?open_import_id=5391a5a8-10fa-4709-84b6-d7cdc1d244bf");
  const sheet=page.getByTestId("import-detail");
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("button",{name:"원고 전체 복사",exact:true})).toBeVisible();
  await sheet.getByRole("tab",{name:"다국어·발행",exact:true}).click();
  const mode=page.getByTestId("manual-publication-mode");
  await expect(mode).toHaveValue("publish");
  const submit=page.getByTestId("manual-publication-submit");
  await expect(submit).toBeEnabled();
  page.once("dialog",dialog=>dialog.dismiss());
  await submit.click();
  expect(requests).toHaveLength(0);
  await mode.selectOption("draft");
  await submit.click();
  await expect.poll(()=>requests.length).toBe(1);
  expect(requests[0].publication_mode).toBe("draft");
  await expect(submit).toBeEnabled();
  await mode.selectOption("publish");
  page.once("dialog",dialog=>dialog.accept());
  await submit.click();
  await expect.poll(()=>requests.length).toBe(2);
  expect(requests[1].publication_mode).toBe("publish");
  expect(requests[1].confirmation).toBe("PUBLISH THIS EXACT MANUSCRIPT PUBLICLY");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
