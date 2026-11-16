import {expect,test} from "playwright/test";

test("keyword authoring starts with the editable professional prompt and submits its versioned direction",async({page})=>{
  const ko="00000000-0000-0000-0000-000000000001";
  const en="00000000-0000-0000-0000-000000000002";
  const submissions:Record<string,unknown>[]=[];
  let publications=0;
  page.on("request",request=>{
    if(request.method()==="POST"&&request.url().includes("manual-live-requests"))publications++;
  });
  await page.route("**/api/keyword-authoring**",async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith("capabilities"))return route.fulfill({json:{
      engine:{available:true,model:"gpt-6-luna",version:"test-only-cli"},
      blogs:[
        {id:ko,display_name:"Trend KO",language_code:"ko",target_country:"KR"},
        {id:en,display_name:"Trend Journal EN",language_code:"en",target_country:"US"},
      ],
      categories:[{slug:"technology",name_ko:"기술"}],
    }});
    if(route.request().method()==="POST"){
      submissions.push(route.request().postDataJSON() as Record<string,unknown>);
      return route.fulfill({status:201,json:{id:"00000000-0000-0000-0000-000000000003",state:"queued"}});
    }
    return route.fulfill({json:{items:[]}});
  });
  await page.goto("/keyword-authoring");
  const direction=page.getByTestId("keyword-authoring-direction");
  await expect(direction).toHaveValue(/국제 주요 언론사/);
  await expect(direction).toHaveValue(/insufficient_evidence/);
  await expect(direction).toHaveValue(/최대 150자/);
  await expect(direction).toHaveValue(/이미지 생성·검색/);
  await direction.fill("요청별 사용자 지침: 독자가 알아야 할 검증된 영향에 집중해줘.");
  await page.getByLabel("대상 Blogger").selectOption(en);
  await expect(direction).toHaveValue("요청별 사용자 지침: 독자가 알아야 할 검증된 영향에 집중해줘.");
  await page.getByRole("button",{name:"기본 프롬프트 복원"}).click();
  await expect(direction).toHaveValue(/국제 주요 언론사/);
  await direction.fill("요청별 사용자 지침: 확인된 사실과 해석을 분리해줘.");
  await page.getByLabel("작성 키워드").fill("verified reporting test topic");
  await page.getByRole("button",{name:"Codex 원고 작성 요청"}).click();
  await expect.poll(()=>submissions.length).toBe(1);
  expect(submissions[0].direction).toBe("요청별 사용자 지침: 확인된 사실과 해석을 분리해줘.");
  expect(submissions[0].direction_prompt_version).toBe("trendjournal-professional-article-v1");
  await page.getByRole("button",{name:"새 요청"}).click();
  await expect(direction).toHaveValue(/국제 주요 언론사/);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(publications).toBe(0);
});
