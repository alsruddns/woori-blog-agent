"use client";

import { useMemo, useRef, useState, type FormEvent } from "react";

type Row = Record<string, unknown>;
const text = (row: Row, key: string) => String(row[key] ?? "");
const esc = (value: string) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const plainAsHtml = (value: string) => value.split(/\n\s*\n/).map(part => part.trim()).filter(Boolean).map(part => {
  if (part.startsWith("### ")) return `<h3>${esc(part.slice(4))}</h3>`;
  if (part.startsWith("## ")) return `<h2>${esc(part.slice(3))}</h2>`;
  const lines = part.split("\n");
  if (lines.every(line => /^[-*] /.test(line))) return `<ul>${lines.map(line => `<li>${esc(line.slice(2))}</li>`).join("")}</ul>`;
  return `<p>${esc(part).replaceAll("\n", "<br>")}</p>`;
}).join("");
function localKst(value: unknown) {
  if (!value) return "";
  const date = new Date(String(value));
  return Number.isNaN(date.valueOf()) ? "" : new Date(date.valueOf() + 9 * 60 * 60 * 1000).toISOString().slice(0, 16);
}

function ArticleEditor({ article, blogs, busy, submit }: {
  article: Row; blogs: Row[]; busy: boolean; submit: (path: string, body: Row) => Promise<void>;
}) {
  const revisions = (article.editorial_versions as Row[] | undefined) ?? [];
  const latest = revisions[0];
  const reviews = (article.review_history as Row[] | undefined) ?? [];
  const publicationJobs = (article.publication_jobs as Row[] | undefined) ?? [];
  const publishedMappings = (article.published_mappings as Row[] | undefined) ?? [];
  const sourceBody = text(article, "body");
  const sourceRows = (article.sources as Row[] | undefined) ?? [];
  const paragraphs = sourceBody.split(/\n\s*\n/).filter(Boolean);
  const initialHtml = text(latest ?? {}, "html_body") || plainAsHtml(text(latest ?? {}, "body") || sourceBody);
  const [htmlBody, setHtmlBody] = useState(initialHtml);
  const [mobile, setMobile] = useState(false);
  const editor = useRef<HTMLTextAreaElement>(null);
  const matchingBlogs = blogs.filter(blog => text(blog, "language_code") === text(article, "language_code"));
  const baseBody = text(latest ?? {}, "body") || sourceBody;

  function insert(before: string, after = "", sample = "선택한 문장") {
    const element = editor.current;
    if (!element) return;
    const start = element.selectionStart, end = element.selectionEnd;
    const selected = htmlBody.slice(start, end) || sample;
    const updated = `${htmlBody.slice(0, start)}${before}${selected}${after}${htmlBody.slice(end)}`;
    setHtmlBody(updated);
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(start + before.length, start + before.length + selected.length);
    });
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const mode = String(form.get("publication_mode") ?? "manual");
    const localDate = String(form.get("planned_publish_at") ?? "");
    const planned = localDate ? new Date(`${localDate}:00+09:00`).toISOString() : null;
    const targetBlogId = String(form.get("target_blog_id") ?? "") || null;
    const existingMapping = publishedMappings.find(record => text(record, "blog_id") === targetBlogId);
    await submit("article-revisions", {
      evaluation_id: text(article, "evaluation_id"), content_version_id: text(article, "content_version_id"),
      base_editorial_version_id: text(latest ?? {}, "id") || null,
      idempotency_key: crypto.randomUUID(), reviewer_name: String(form.get("reviewer_name") ?? ""),
      reason: String(form.get("reason") ?? ""), title: String(form.get("title") ?? ""),
      body: "", html_body: htmlBody, summary: String(form.get("seo_description") ?? ""),
      keywords: String(form.get("keywords") ?? "").split("|").map(value => value.trim()).filter(Boolean),
      seo_description: String(form.get("seo_description") ?? ""),
      blogger_labels: String(form.get("blogger_labels") ?? "").split(",").map(value => value.trim()).filter(Boolean),
      target_blog_id: targetBlogId,
      existing_remote_post_id: text(existingMapping ?? {}, "remote_post_id") || text(latest ?? {}, "existing_remote_post_id") || null,
      publication_mode: mode, planned_publish_at: planned,
    });
  }

  function startReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void submit("article-review-events", {
      evaluation_id: text(article, "evaluation_id"), content_version_id: text(article, "content_version_id"),
      idempotency_key: crypto.randomUUID(), reviewer_name: String(form.get("reviewer_name") ?? ""),
    });
  }

  function recordReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void submit("article-reviews", {
      evaluation_id: text(article, "evaluation_id"), content_version_id: text(article, "content_version_id"),
      editorial_version_id: String(form.get("editorial_version_id") ?? "") || null,
      idempotency_key: crypto.randomUUID(), reviewer_name: String(form.get("reviewer_name") ?? ""),
      factual_accuracy: String(form.get("factual_accuracy") ?? "not_assessed"),
      translation_naturalness: String(form.get("translation_naturalness") ?? "not_assessed"),
      reader_value: String(form.get("reader_value") ?? "not_assessed"),
      disposition: String(form.get("disposition") ?? "reviewed"), comments: String(form.get("comments") ?? ""),
      requested_changes: String(form.get("requested_changes") ?? ""),
    });
  }

  const safePreviewDocument = `<!doctype html><html lang="${esc(text(article, "language_code"))}"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(text(latest ?? {}, "title") || text(article, "title"))}</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:${mobile ? "390px" : "760px"};margin:24px auto;padding:0 18px;color:#222}h2{margin-top:1.8em}a{color:#0759a5}blockquote{border-left:3px solid #bbb;padding-left:1em;color:#555}</style></head><body><header><h1>${esc(text(latest ?? {}, "title") || text(article, "title"))}</h1><p>${esc(text(latest ?? {}, "seo_description") || text(article, "summary"))}</p></header>${htmlBody}</body></html>`;
  const status = text(article, "editorial_status") || "unreviewed";

  return <article style={{ border: "1px solid #bbb", padding: 16, marginBlock: 16 }}>
    <h3>{text(article, "topic")} · {text(article, "language_code")} · 원고 v{text(article, "content_version")}</h3>
    <p>편집 검토: {status} · 기계 검사: {article.machine_passed ? "통과" : "보류"} · 발행 승인: 별도 필요 · 실제 발행 차단 · publish_ready=false</p>
    {publicationJobs.length > 0 ? <p>발행 작업 기록: {publicationJobs.map(job => `${text(job, "language_code")} ${text(job, "url")} ${text(job, "publication_state")} ${text(job, "simulation_only") === "true" ? "Mock" : "운영 상태 확인 필요"}`).join(" · ")}</p> : <p>발행 작업: 기록 없음</p>}
    {publishedMappings.length > 0 ? <p>기존 Blogger 게시 매핑: {publishedMappings.map(record => `${text(record, "language_code")} ${text(record, "url")} · 기존 게시글 ID ${text(record, "remote_post_id")} · 게시 ${text(record, "published_at")}`).join(" / ")} — 향후 수정은 해당 ID의 기존 글 갱신 대상입니다. 현재 실제 쓰기는 차단되어 있습니다.</p> : <p>이 원고 버전에 연결된 실제 Blogger 게시글 ID 없음</p>}
    <details><summary>출처·사실 원장·실패 이유</summary>
      <p>출처 {JSON.stringify(article.source_ids ?? [])} · 사실 {JSON.stringify(article.fact_ids ?? [])}</p>
      <h4>문단별 출처 연결</h4>{paragraphs.map((paragraph, index) => {
        const citations = [...paragraph.matchAll(/\[source:([0-9a-f-]{36})\]/gi)].map(match => match[1]);
        const display = paragraph.replace(/\[source:([0-9a-f-]{36})\]/gi, (_marker, id: string) => `〔${sourceRows.find(source => text(source, "id") === id)?.source_name ?? "출처 ID 미확인"}〕`);
        return <p key={`${index}-${paragraph.slice(0, 24)}`} style={{ whiteSpace: "pre-wrap" }}>{display}<small> · {citations.length ? citations.map(id => sourceRows.find(source => text(source, "id") === id)?.source_name ?? "출처 ID 미확인").join(", ") : "출처 표식 미검출"}</small></p>;
      })}
      {sourceRows.map(source => <p key={text(source, "id")}>{text(source, "source_name")} · 기준일 {text(source, "published_at")} · 수집 {text(source, "collected_at")} · 권리 {text(source, "rights")} · <a href={text(source, "url")} target="_blank" rel="noreferrer">원문</a></p>)}
      {(article.facts as Row[] | undefined ?? []).map(fact => <p key={text(fact, "id")}>{text(fact, "fact_key")}: {text(fact, "source_excerpt")} · 숫자 {JSON.stringify(fact.numeric_values ?? [])} · 날짜 {JSON.stringify(fact.date_values ?? [])}</p>)}
      <pre>{JSON.stringify({ checks: article.checks, proper_name_candidates: article.proper_name_candidates }, null, 2)}</pre>
    </details>
    <details><summary>저장 버전 비교</summary>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 16 }}>
        <section><h4>기준 원고 v{text(article, "content_version")}</h4><pre style={{ whiteSpace: "pre-wrap" }}>{sourceBody}</pre></section>
        <section><h4>최신 편집본 {latest ? `v${text(latest, "revision_number")}` : "없음"}</h4><pre style={{ whiteSpace: "pre-wrap" }}>{baseBody}</pre></section>
      </div>
      {revisions.map(revision => <p key={text(revision, "id")}>편집 v{text(revision, "revision_number")} · 작성자 {text(revision, "reviewer_name")} · {text(revision, "created_at")} · {text(revision, "quality_status")} · SHA {text(revision, "body_sha256")}</p>)}
    </details>
    <form onSubmit={event => void save(event)}>
      <h4>새 원고 버전 편집</h4>
      <label>작성자 <input name="reviewer_name" required minLength={2} maxLength={80}/></label>
      <label>변경 사유 <input name="reason" required minLength={10} maxLength={2000}/></label>
      <label>제목 <input name="title" defaultValue={text(latest ?? {}, "title") || text(article, "title")} required maxLength={500}/></label>
      <label>SEO 설명 <textarea name="seo_description" defaultValue={text(latest ?? {}, "seo_description") || text(article, "summary")} required minLength={10} maxLength={500}/></label>
      <label>검색 키워드 (| 구분) <input name="keywords" defaultValue={((latest?.keywords ?? article.keywords) as string[] | undefined)?.join(" | ") ?? ""} required/></label>
      <label>Blogger 라벨 (쉼표 구분) <input name="blogger_labels" defaultValue={((latest?.blogger_labels ?? []) as string[]).join(", ")}/></label>
      <label>대상 언어별 블로그 <select name="target_blog_id" defaultValue={text(latest ?? {}, "target_blog_id") || text(publishedMappings[0] ?? {}, "blog_id")}>
        <option value="">미지정</option>{matchingBlogs.map(blog => <option key={text(blog, "id")} value={text(blog, "id")} disabled={publishedMappings.length > 0 && !publishedMappings.some(record => text(record, "blog_id") === text(blog, "id"))}>{text(blog, "url")} · {text(blog, "active") === "true" ? "활성" : "비활성"}</option>)}
      </select></label>
      <label>발행 모드 <select name="publication_mode" defaultValue={text(latest ?? {}, "publication_mode") || "manual"}>
        <option value="draft">초안 저장</option><option value="manual">수동 게시 준비 (기본)</option><option value="scheduled">승인 후 예약 게시</option>
      </select></label>
      <label>게시/예약 희망 시각 (KST) <input name="planned_publish_at" type="datetime-local" defaultValue={localKst(latest?.planned_publish_at)}/></label>
      <p>모드와 게시 시각은 편집 설정으로 버전 보존됩니다. 예약 또는 모드 선택만으로 발행 작업이 생성되지 않습니다. 실제 Blogger 쓰기와 자동 발행은 계속 비활성화되어 있습니다.</p>
      <div aria-label="본문 서식 도구" style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBlock: 8 }}>
        <button type="button" onClick={() => insert("<h2>", "</h2>", "소제목")}>H2</button>
        <button type="button" onClick={() => insert("<h3>", "</h3>", "소제목")}>H3</button>
        <button type="button" onClick={() => insert("<strong>", "</strong>", "강조할 문장")}>굵게</button>
        <button type="button" onClick={() => insert("<em>", "</em>", "강조할 문장")}>기울임</button>
        <button type="button" onClick={() => insert("<ul><li>", "</li></ul>", "목록 항목")}>목록</button>
        <button type="button" onClick={() => insert("<blockquote>", "</blockquote>", "인용 문장")}>인용</button>
        <button type="button" onClick={() => insert("<p>", "</p>", "문단")}>문단</button>
      </div>
      <label>본문 HTML (저장 전 서버 허용 목록으로 정화)<textarea ref={editor} name="html_body" value={htmlBody} onChange={event => setHtmlBody(event.target.value)} required maxLength={100000} rows={18} spellCheck/></label>
      <p>저장 시 허용된 문단·H2/H3·목록·강조·HTTPS 링크만 보존합니다. 스크립트, 이벤트 속성, 위험한 URL은 제거합니다. 원문 버전은 변경하지 않고 새 버전에서 모든 품질 검사를 다시 실행합니다.</p>
      <label>삽입할 링크 주소 (HTTPS) <input type="url" id={`link-${text(article, "evaluation_id")}`} placeholder="https://..."/></label>
      <button type="button" onClick={() => {
        const link = document.getElementById(`link-${text(article, "evaluation_id")}`) as HTMLInputElement | null;
        const value = link?.value.trim() ?? "";
        if (!value.startsWith("https://")) return;
        insert(`<a href="${value.replaceAll("&", "&amp;").replaceAll('"', "&quot;")}">`, "</a>", "링크 문구");
      }}>선택 문장에 링크</button>{" "}
      <button disabled={busy}>새 버전 저장 및 품질 재검사</button>
    </form>
    <section aria-label="미리보기">
      <h4>게시 형태 미리보기 · {mobile ? "모바일" : "데스크톱"}</h4>
      <button type="button" onClick={() => setMobile(value => !value)}>미리보기 폭 전환</button>
      <iframe title={`${text(article, "language_code")} 원고 미리보기`} sandbox="" srcDoc={safePreviewDocument}
        style={{ width: "100%", height: mobile ? 720 : 560, border: "1px solid #888", background: "white" }}/>
    </section>
    <details><summary>사람 검토 기록 ({reviews.length})</summary>{reviews.map(review => <p key={text(review, "id")}>
      {text(review, "reviewer_name")} · {text(review, "disposition")} · 사실 {text(review, "factual_accuracy")} · 번역 {text(review, "translation_naturalness")} · 독자 가치 {text(review, "reader_value")} · {text(review, "created_at")}<br/>
      {text(review, "comments")}<br/>수정 요청: {text(review, "requested_changes") || "없음"}
    </p>)}</details>
    <form onSubmit={startReview}><label>검토 시작자 <input name="reviewer_name" required minLength={2} maxLength={80}/></label>
      <button disabled={busy}>검토 시작 이력 추가</button></form>
    <form onSubmit={recordReview}>
      <h4>사람 편집 검토</h4><label>검토자 <input name="reviewer_name" required minLength={2} maxLength={80}/></label>
      <label>검토 대상 <select name="editorial_version_id"><option value="">기준 원고 v{text(article, "content_version")}</option>{revisions.filter(revision => Boolean(revision.machine_passed)).map(revision => <option key={text(revision, "id")} value={text(revision, "id")}>편집 v{text(revision, "revision_number")} · 기계 검사 통과</option>)}</select></label>
      <label>사실 정확성 <select name="factual_accuracy"><option value="not_assessed">미평가</option><option value="verified">확인</option><option value="issue_found">문제 발견</option><option value="uncertain">불확실</option></select></label>
      <label>자연스러움 <select name="translation_naturalness"><option value="not_assessed">미평가</option><option value="acceptable">수용 가능</option><option value="issue_found">문제 발견</option><option value="uncertain">불확실</option></select></label>
      <label>독자 가치 <select name="reader_value"><option value="not_assessed">미평가</option><option value="useful">유용</option><option value="insufficient">부족</option><option value="uncertain">불확실</option></select></label>
      <label>편집 결과 <select name="disposition"><option value="reviewed">검토 기록</option><option value="revision_requested">수정 필요</option><option value="rejected">반려</option><option value="approved">편집 검토 통과</option></select></label>
      <label>검토 의견 <textarea name="comments" required minLength={10} maxLength={2000}/></label>
      <label>수정 요청 <textarea name="requested_changes" maxLength={2000}/></label>
      <p>편집 검토 통과는 발행 승인과 분리됩니다. 실제 Blogger 게시 및 예약 실행은 이 화면에서 활성화되지 않습니다.</p>
      <button disabled={busy}>사람 검토 결과 추가</button>
    </form>
  </article>;
}

export default function ManuscriptManager({ articles, blogs, categories, busy, publications, submit }: {
  articles: Row[]; blogs: Row[]; categories: Row[]; busy: boolean; publications: Row[]; submit: (path: string, body: Row) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [language, setLanguage] = useState("");
  const [blogId, setBlogId] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("newest");
  const [compareIds, setCompareIds] = useState<[string, string]>(["", ""]);
  const filtered = useMemo(() => articles.filter(article => {
    const revisions = (article.editorial_versions as Row[] | undefined) ?? [];
    const target = text(revisions[0] ?? {}, "target_blog_id");
    const articleJobs = publications.filter(job => text(job, "content_version_id") === text(article, "content_version_id"));
    const posted = ((article.published_mappings as Row[] | undefined) ?? []).length > 0;
    const editorialStatus = text(article, "editorial_status");
    const publicationMatches = articleJobs.some(job => text(job, "status") === status || text(job, "publication_state") === status);
    const statusMatches = !status
      || (status === "quality_held" && !article.machine_passed)
      || (status === "draft" && editorialStatus === "unreviewed")
      || (status === "approved" && editorialStatus === "editorial_review_passed")
      || (status === "scheduled" && (text(revisions[0] ?? {}, "publication_mode") === "scheduled"
        || articleJobs.some(job => text(job, "status") === "queued" || text(job, "publication_state") === "publication_queued")))
      || (status === "published" && (posted || articleJobs.some(job => text(job, "publication_state") === "published")))
      || (status === "publication_failed" && articleJobs.some(job => text(job, "status") === "failed" || text(job, "publication_state") === "publication_failed"))
      || (status !== "quality_held" && status !== "draft" && status !== "approved" && status !== "scheduled"
        && status !== "published" && status !== "publication_failed" && (publicationMatches || editorialStatus === status));
    return (!query || `${text(revisions[0] ?? {}, "title") || text(article, "title")} ${text(article, "topic")}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
      && (!language || text(article, "language_code") === language)
      && (!category || text(article, "category_slug") === category)
      && statusMatches
      && (!blogId || (text(article, "language_code") === text(blogs.find(blog => text(blog, "id") === blogId) ?? {}, "language_code") && (!target || target === blogId)));
  }).sort((a, b) => {
    const aTime = new Date(text((a.editorial_versions as Row[] | undefined)?.[0] ?? a, "created_at")).valueOf();
    const bTime = new Date(text((b.editorial_versions as Row[] | undefined)?.[0] ?? b, "created_at")).valueOf();
    return (sort === "oldest" ? 1 : -1) * (aTime - bTime);
  }).map(article => ({
    ...article,
    publication_jobs: publications.filter(job => text(job, "content_version_id") === text(article, "content_version_id")),
  } as Row)), [articles, blogs, blogId, category, language, publications, query, sort, status]);
  const byId = (id: string) => articles.find(article => text(article, "evaluation_id") === id);
  const left = byId(compareIds[0]), right = byId(compareIds[1]);
  const languages = [...new Set(articles.map(article => text(article, "language_code")))].sort();

  return <section aria-labelledby="manuscripts-heading">
    <h2 id="manuscripts-heading">원고 관리·편집</h2>
    <p>저장된 원고 {articles.length}건을 표시합니다. 원본과 이전 기록을 보존하며 수정은 새 버전으로 저장됩니다. 승인·예약 설정만으로 게시하지 않으며, Blogger 실제 쓰기는 비활성화 상태입니다.</p>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
      <label>제목 검색 <input value={query} onChange={event => setQuery(event.target.value)} type="search"/></label>
      <label>언어 <select value={language} onChange={event => setLanguage(event.target.value)}><option value="">모든 언어</option>{languages.map(value => <option key={value}>{value}</option>)}</select></label>
      <label>블로그 <select value={blogId} onChange={event => setBlogId(event.target.value)}><option value="">모든 블로그</option>{blogs.map(blog => <option key={text(blog, "id")} value={text(blog, "id")}>{text(blog, "language_code")} · {text(blog, "url")}</option>)}</select></label>
      <label>카테고리 <select value={category} onChange={event => setCategory(event.target.value)}><option value="">모든 카테고리</option>{categories.map(item => <option key={text(item, "slug")} value={text(item, "slug")}>{text(item, "slug")}</option>)}</select></label>
      <label>상태 <select value={status} onChange={event => setStatus(event.target.value)}><option value="">모든 상태</option><option value="draft">초안·미검토</option><option value="in_review">검토 중</option><option value="revision_needed">수정 필요 · 사람 검토</option><option value="quality_held">수정 필요 · 품질 보류</option><option value="approved">편집 검토 통과</option><option value="scheduled">예약 계획 또는 작업</option><option value="published">실제 게시 상태</option><option value="publication_failed">발행 실패</option></select></label>
      <label>정렬 <select value={sort} onChange={event => setSort(event.target.value)}><option value="newest">최근 수정·작성</option><option value="oldest">오래된 순</option></select></label>
    </div>
    <p>표시 {filtered.length} / 전체 {articles.length}건</p>
    {filtered.map(article => {
      const latest = (article.editorial_versions as Row[] | undefined)?.[0];
      return <ArticleEditor key={`${text(article, "evaluation_id")}-${text(latest ?? {}, "id")}`} article={article} blogs={blogs} busy={busy} submit={submit}/>;
    }) }
    <section><h3>원고 버전 비교</h3>
      {[0, 1].map(index => <label key={index}>비교 원고 {index + 1}<select value={compareIds[index]} onChange={event => setCompareIds(current => current.map((value, item) => item === index ? event.target.value : value) as [string, string])}>
        <option value="">원고 선택</option>{articles.map(article => <option key={text(article, "evaluation_id")} value={text(article, "evaluation_id")}>{text(article, "language_code")} · {text(article, "topic")}</option>)}
      </select></label>)}
      {left && right ? <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: 16 }}>
        {[left, right].map((article, index) => <article key={`${text(article, "evaluation_id")}-${index}`}><h4>{text(article, "language_code")} · {text(article, "title")}</h4><pre style={{ whiteSpace: "pre-wrap" }}>{text(article, "body")}</pre></article>)}
      </div> : <p>비교할 원고 두 개를 선택하세요.</p>}
    </section>
  </section>;
}
