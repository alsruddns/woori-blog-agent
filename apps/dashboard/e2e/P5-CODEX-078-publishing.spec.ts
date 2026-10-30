import { expect, test } from "playwright/test";

test("publishing reuses detail, keeps filters, and explicit manual confirmation refreshes Jobs", async ({page})=>{
  let posts=0, monitorReads=0;
  // All publishing mutations are intercepted: this test never approves a real post.
  await page.route("**/api/publications/manual-live-requests",async route=>{
    posts++;
    const data=route.request().postDataJSON();
    expect(data.actor_label).toBe("admin");expect(data.reason).toBe("확인완료");
    expect(data.reviewed_exact_content).toBe(true);
    await new Promise(resolve=>setTimeout(resolve,300));
    await route.fulfill({json:{id:"test-only-job",recorded:true,followup_count:2}});
  });
  await page.route("**/api/publications/worker-jobs?*",async route=>{monitorReads++;await route.continue();});
  await page.route("**/api/publications/scheduled-auto-state?*",async route=>{
    const response=await route.fetch({headers:{...route.request().headers(),origin:new URL(route.request().url()).origin}});const data=await response.json();
    for(const target of data.targets??[]){if(target.manual_publication){target.manual_publication.eligible=true;target.manual_publication.blockers=[];target.manual_publication.jobs=[];}}
    await route.fulfill({json:data});
  });
  await page.goto("/publishing?view=auto_failure&page=1");
  const table=page.locator(".publication-manager > .workspace-panel .publication-table-scroll").last();
  const row=table.locator("tbody tr").first();
  await expect(row).toBeVisible();
  await row.locator("td").first().getByRole("button").click();
  const sheet=page.getByTestId("import-detail");await expect(sheet).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/publishing");
  await sheet.getByRole("button",{name:"닫기",exact:true}).click();
  await expect(sheet).toHaveCount(0);await page.waitForTimeout(150);
  expect(new URL(page.url()).searchParams.get("view")).toBe("auto_failure");
  expect(new URL(page.url()).searchParams.has("open_import_id")).toBe(false);
  await row.getByRole("button",{name:"Blogger에 수동 발행"}).click();
  await expect(sheet.locator("#manual-blogger-publication")).toBeVisible();
  const checks=sheet.locator(".manual-publication-checks input");
  expect(await checks.count()).toBe(3);
  for(const c of await checks.all())await expect(c).toBeChecked();
  const boxes=await checks.evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));
  expect(boxes[1]).toBeGreaterThan(boxes[0]);expect(boxes[2]).toBeGreaterThan(boxes[1]);
  await expect(sheet.getByLabel("게시 승인자 표시 이름")).toHaveValue("admin");
  expect(posts).toBe(0);
  const before=monitorReads;
  page.once("dialog",dialog=>dialog.accept());
  await sheet.getByTestId("manual-publication-submit").click();
  await expect(sheet.getByTestId("manual-publication-submit")).toBeDisabled();
  await expect(sheet.getByRole("status").filter({hasText:"test-only-job"})).toBeVisible();
  expect(posts).toBe(1);
  await expect.poll(()=>monitorReads).toBeGreaterThan(before);
  expect(new URL(page.url()).pathname).toBe("/publishing");
  await expect(sheet.getByTestId("manual-publication-submit")).toBeEnabled();
  await page.keyboard.press("Escape");await expect(sheet).toHaveCount(0);
});
