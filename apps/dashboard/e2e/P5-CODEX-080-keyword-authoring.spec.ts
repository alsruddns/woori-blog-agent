import {expect,test} from "playwright/test";

test("keyword request is idempotent, review stays in place, and no publication is requested",async({page})=>{
  const blog="00000000-0000-0000-0000-000000000001",job="00000000-0000-0000-0000-000000000002",importId="00000000-0000-0000-0000-000000000003",version="00000000-0000-0000-0000-000000000004";
  let posts=0,publications=0;
  page.on("request",r=>{if(r.method()==="POST"&&r.url().includes("manual-live-requests"))publications++;});
  await page.route("**/api/keyword-authoring**",async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith("capabilities"))return route.fulfill({json:{engine:{available:true,model:"gpt-6-luna",version:"test-only-cli"},blogs:[{id:blog,display_name:"격리 한국어 대상",language_code:"ko",target_country:"KR"}],categories:[{slug:"technology",name_ko:"IT"}]}});
    if(route.request().method()==="POST"){posts++;const body=route.request().postDataJSON();expect(body.keyword).toBe("파이썬 문자열 가이드");expect(body.blog_id).toBe(blog);expect(body.request_key).toBeTruthy();return route.fulfill({json:{id:job,state:"queued"}});}
    return route.fulfill({json:{items:posts?[{id:job,keyword:"파이썬 문자열 가이드",blog_id:blog,language_code:"ko",model:"gpt-6-luna",state:"imported_review",import_id:importId,content_version_id:version,created_at:"2026-10-30T08:00:00Z"}]:[]}});
  });
  await page.route(`**/api/research/content-imports/${importId}`,route=>route.fulfill({json:{item:{external_content_id:job,language_code:"ko",source_region:"ZZ",category:"technology",generation_method:"manual_codex_import",title:"격리 UI 원고",sources:[],claims:[]},latest_version:{id:version,content_version_id:version,title:"격리 UI 원고",body_markdown:"테스트 전용 본문이며 실제 원고나 게시물이 아닙니다.",version_number:1},versions:[],assessments:[],reviews:[],editorial_review_status:"awaiting_human_review",localization_requests:[],mock_publications:[]}}));
  await page.route("**/api/publications/scheduled-auto-state?*",route=>route.fulfill({json:{targets:[],scheduled:false}}));
  await page.goto("/keyword-authoring");
  await expect(page.getByRole("heading",{name:"키워드 원고 작성",exact:true})).toBeVisible();
  await page.getByLabel("작성 키워드",{exact:true}).fill("파이썬 문자열 가이드");
  await expect(page.getByLabel("작성 언어",{exact:true})).toHaveValue("ko");
  await page.getByRole("button",{name:"Codex 원고 작성 요청"}).dblclick();
  await expect(page.getByText("Import 완료 · 사용자 검토 대기",{exact:true})).toBeVisible();
  expect(posts).toBe(1);
  await page.getByLabel("화면 테마").selectOption("dark");
  await page.screenshot({path:`.playwright-mcp/P5-CODEX-080-${test.info().project.name}.png`});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole("button",{name:"원고 검토·수정"}).click();
  await expect(page.getByTestId("import-detail")).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/keyword-authoring");
  await page.getByTestId("import-detail").getByRole("button",{name:"닫기",exact:true}).click();
  await expect(page.getByTestId("import-detail")).toHaveCount(0);
  expect(publications).toBe(0);
});
