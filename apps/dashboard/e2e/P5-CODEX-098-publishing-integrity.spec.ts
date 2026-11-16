import { expect, test } from "playwright/test";

test.beforeEach(async({page})=>{
  // Read-only operational verification; no mutation reaches the application.
  await page.route("**/api/**",route=>route.request().method()==="GET"?route.continue():route.abort());
});

test("paused automatic job is absent from dispatch queue and opens its exact manuscript",async({page})=>{
  await page.goto("/publishing?view=queue");
  await expect(page.locator(".publication-section tbody tr")).toHaveCount(0);
  const queue=await page.evaluate(async()=>await (await fetch('/api/publications?view=queue')).json());
  expect(queue.summary.queue).toBe(0);
  expect(queue.mode_policy.emergency_stopped).toBe(true);
  expect(queue.real_writes_enabled).toBe(false);
  await page.goto("/publishing?view=held&q=Jamie");
  const section=page.locator(".publication-section");
  const title=section.locator('button.import-title').first();
  await expect(title).toContainText("Jamie Carragher and Aston Villa");
  const listed=await title.innerText();
  await expect(section).toContainText("자동 발행 중지로 보류");
  await title.click();
  const sheet=page.getByTestId('import-detail');
  await expect(sheet.getByTestId('import-title-input')).toHaveValue(listed);
  expect(new URL(page.url()).pathname).toBe('/publishing');
  expect(new URL(page.url()).searchParams.get('q')).toBe('Jamie');
  await sheet.getByRole('tab',{name:'다국어·발행',exact:true}).click();
  await expect(sheet.getByTestId('manual-publication-mode')).toHaveValue('publish');
  await expect(sheet.getByTestId('manual-publication-submit')).toBeDisabled();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test("verified Fed publication is resolved, with consistent list and detail titles",async({page})=>{
  await page.goto('/publishing?view=published&q=Cook');
  const section=page.locator('.publication-section');
  const title=section.locator('button.import-title').first();
  await expect(title).toHaveText("Cook and Hammack's FOMC dissent: a preference for a higher rate");
  await expect(section).toContainText('3006185544912270190');
  await expect(section).toContainText('게시 당시 제목:');
  const listed=await title.innerText();
  await title.click();
  await expect(page.getByTestId('import-title-input')).toHaveValue(listed);
  await page.getByTestId('import-detail').getByRole('tab',{name:'변경 이력',exact:true}).click();
  await expect(page.getByTestId('import-detail')).toContainText('What the Fed');
  await page.goto('/publishing?view=auto_failure');
  const failures=await page.evaluate(async()=>await(await fetch('/api/publications?view=auto_failure&page_size=100')).json());
  expect(failures.items.some((item:{import_id?:string})=>item.import_id==='7bcc3d86-d0aa-4d6c-bef4-e47726b7f818')).toBe(false);
  expect(failures.summary.auto_failure).toBe(failures.total_count);
  await page.getByPlaceholder('검색어').fill('nonexistent-p098-search-result');
  await page.locator('.publication-section').getByRole('button',{name:'검색',exact:true}).click();
  await expect(page.locator('.publication-section tbody tr')).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
