"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type { Config } from "./types";

export default function Manager({ config }: { config: Config }) {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  async function submit(
    event: FormEvent<HTMLFormElement>,
    resource: string,
    method = "POST",
    active = false,
  ) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const body: Record<string, FormDataEntryValue | boolean> =
      Object.fromEntries(fields);
    for (const key of ["official_translation", "approved"]) body[key] = fields.get(key) === "on";
    const suffix = body._id ? `/${encodeURIComponent(String(body._id))}` : "";
    delete body._id;
    if (active) body.active = fields.get("active") === "on";
    setPending(true);
    setMessage("");
    try {
      const response = await fetch(`/api/config/${resource}${suffix}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        setMessage(
          `저장 실패 (${response.status}). 입력 형식과 기존 참조 관계를 확인하세요.`,
        );
        return;
      }
      setMessage("저장했습니다. 감사 이력이 기록되었습니다.");
      router.refresh();
    } catch {
      setMessage("서버 연결에 실패했습니다.");
    } finally {
      setPending(false);
    }
  }
  const languageOptions = config.languages.map((l) => (
    <option key={l.code} value={l.code}>
      {l.code} · {l.display_name}
    </option>
  ));
  const profileOptions = config.profiles.map((p) => (
    <option key={p.id} value={p.id}>
      {p.language_code} · {p.target_country || "공통"}
    </option>
  ));
  const blogOptions = config.blogs.map((b) => (
    <option key={b.id} value={b.id}>
      {b.display_name} · {b.language_code}
    </option>
  ));
  return (
    <>
      <p role="status" aria-live="polite">
        {message}
      </p>
      <h2>등록 언어 ({config.languages.length})</h2>
      <div className="grid">
        {config.languages.map((l) => (
          <article key={l.code}>
            <h3>
              {l.code} · {l.display_name}
            </h3>
            <p>{l.active ? "활성" : "비활성 · 기존 기록 보존"}</p>
          </article>
        ))}
      </div>
      <fieldset disabled={pending}>
        <legend>언어 등록</legend>
        <form onSubmit={(e) => submit(e, "languages", "POST", true)}>
          <label>
            BCP 47 코드
            <input
              name="code"
              placeholder="es, pt-BR, zh-TW"
              required
              maxLength={100}
            />
          </label>
          <label>
            표시 이름
            <input name="display_name" required maxLength={100} />
          </label>
          <label>
            <input type="checkbox" name="active" defaultChecked />
            활성
          </label>
          <button>언어 등록</button>
        </form>
      </fieldset>
      <fieldset disabled={pending}>
        <legend>언어 이름·활성 상태 변경</legend>
        <form onSubmit={(e) => submit(e, "languages", "PATCH", true)}>
          <label>
            언어
            <select name="_id" required>
              {languageOptions}
            </select>
          </label>
          <label>
            표시 이름
            <input name="display_name" required maxLength={100} />
          </label>
          <label>
            <input type="checkbox" name="active" defaultChecked />
            활성 (해제하면 비활성화)
          </label>
          <button>변경 저장</button>
        </form>
      </fieldset>
      <h2>Blogger 연결 설정</h2>
      <div className="grid">
        {config.blogs.map((b) => (
          <article key={b.id}>
            <h3>{b.display_name}</h3>
            <a href={b.url} target="_blank" rel="noreferrer">
              {b.url}
            </a>
            <p>
              {b.language_code} · {b.active ? "활성" : "비활성"}
            </p>
            <small>Blog ID: {b.blog_id ?? "API 조회 대기"}</small>
          </article>
        ))}
      </div>
      <fieldset disabled={pending}>
        <legend>블로그 주소 등록 (동일 언어 복수 등록 가능)</legend>
        <form onSubmit={(e) => submit(e, "blogs", "POST", true)}>
          <label>
            언어
            <select name="language_code" required>
              {languageOptions}
            </select>
          </label>
          <label>
            표시 이름
            <input name="display_name" required maxLength={100} />
          </label>
          <label>
            Blogspot 주소
            <input
              name="url"
              type="url"
              placeholder="https://example.blogspot.com"
              required
            />
          </label>
          <label>
            <input name="active" type="checkbox" defaultChecked />
            활성
          </label>
          <button>블로그 등록</button>
        </form>
      </fieldset>
      <fieldset disabled={pending}>
        <legend>블로그 이름·활성 상태 변경</legend>
        <form onSubmit={(e) => submit(e, "blogs", "PATCH", true)}>
          <label>
            블로그
            <select name="_id" required>
              {blogOptions}
            </select>
          </label>
          <label>
            표시 이름
            <input name="display_name" required maxLength={100} />
          </label>
          <label>
            <input name="active" type="checkbox" defaultChecked />
            활성
          </label>
          <button>변경 저장</button>
        </form>
      </fieldset>
      <h2>국가별 콘텐츠·현지화·SEO 정책</h2>
      <p>
        같은 언어·대상 국가의 정책을 전체 저장합니다. 언어와 국가는 별도로
        관리합니다.
      </p>
      <div className="grid">
        {config.profiles.map((p) => (
          <article key={p.id}>
            <h3>
              {p.language_code} / {p.target_country || "공통"}
            </h3>
            <p>검색 의도: {p.search_intent || "미설정"}</p>
            <p>생성: {p.generation_policy || "미설정"}</p>
            <p>현지화: {p.localization_policy || "미설정"}</p>
            <p>SEO: {p.seo_policy || "미설정"}</p>
          </article>
        ))}
      </div>
      <fieldset disabled={pending}>
        <legend>국가별 정책 저장</legend>
        <form onSubmit={(e) => submit(e, "profiles")}>
          <label>
            언어
            <select name="language_code" required>
              {languageOptions}
            </select>
          </label>
          <label>
            대상 국가
            <input
              name="target_country"
              placeholder="US, GB, KR (공통은 빈 값)"
              pattern="([A-Z]{2}|[0-9]{3})?"
            />
          </label>
          {[
            ["search_intent", "검색 의도"],
            ["generation_policy", "콘텐츠 생성 정책"],
            ["localization_policy", "번역·현지화 정책"],
            ["seo_policy", "SEO 검증 정책"],
          ].map(([name, label]) => (
            <label key={name}>
              {label}
              <textarea name={name} maxLength={2000} />
            </label>
          ))}
          <button>정책 전체 저장</button>
        </form>
      </fieldset>
      <h2>발행 스케줄</h2>
      <p>
        예약 설정만 저장합니다. Phase 1에서는 스케줄 실행과 자동 발행이
        차단됩니다.
      </p>
      <ul>
        {config.policies.map((p) => (
          <li key={p.id}>
            {config.blogs.find((b) => b.id === p.blog_id)?.display_name} ·{" "}
            {config.profiles.find((r) => r.id === p.profile_id)
              ?.target_country || "공통"}{" "}
            · {p.schedule_cron} ({p.timezone}) ·{" "}
            {p.active ? "정책 활성" : "정책 비활성"} · 자동 발행 차단
          </li>
        ))}
      </ul>
      <fieldset disabled={pending}>
        <legend>스케줄 저장</legend>
        <form onSubmit={(e) => submit(e, "policies", "POST", true)}>
          <label>
            블로그
            <select name="blog_id" required>
              {blogOptions}
            </select>
          </label>
          <label>
            언어·국가 정책
            <select name="profile_id" required>
              {profileOptions}
            </select>
          </label>
          <label>
            IANA 시간대
            <input name="timezone" defaultValue="Asia/Seoul" required />
          </label>
          <label>
            5필드 cron
            <input name="schedule_cron" defaultValue="0 9 * * *" required />
          </label>
          <label>
            <input type="checkbox" name="active" />
            정책 활성 (자동 발행 허용과 별개)
          </label>
          <button>스케줄 저장</button>
        </form>
      </fieldset>
      <h2>언어·국가·블로그별 준비 상태</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {[
                "언어 / 국가",
                "블로그",
                "생성",
                "번역",
                "품질 검증",
                "Blogger 연결",
                "테스트 발행",
                "자동 발행",
              ].map((x) => (
                <th key={x}>{x}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {config.readiness.map((r, i) => (
              <tr key={`${r.profile_id}-${r.connection_id ?? i}`}>
                <td>
                  {r.language_code} / {r.target_country || "공통"}
                </td>
                <td>
                  {config.blogs.find((b) => b.id === r.connection_id)
                    ?.display_name || "미등록"}
                </td>
                {[
                  r.generation_possible,
                  r.translation_possible,
                  r.quality_possible,
                  r.blogger_connected,
                  r.test_publish_verified,
                  r.automatic_publishing_allowed,
                ].map((v, j) => (
                  <td key={j}>{v ? "가능" : "미검증 / 차단"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>카테고리와 용어집</h2>
      <fieldset disabled={pending}>
        <legend>공통 카테고리 등록</legend>
        <form onSubmit={(e) => submit(e, "categories")}>
          <label>
            식별자
            <input
              name="slug"
              required
              pattern="[a-z0-9]+(-[a-z0-9]+)*"
              maxLength={100}
            />
          </label>
          <button>카테고리 등록</button>
        </form>
      </fieldset>
      <fieldset disabled={pending}>
        <legend>국가별 카테고리 명칭</legend>
        <form onSubmit={(e) => submit(e, "category-localizations")}>
          <label>
            카테고리
            <select name="category_id" required>
              {config.categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.slug}
                </option>
              ))}
            </select>
          </label>
          <label>
            언어·국가
            <select name="profile_id" required>
              {profileOptions}
            </select>
          </label>
          <label>
            표시 이름
            <input name="display_name" required maxLength={100} />
          </label>
          <button>명칭 저장</button>
        </form>
      </fieldset>
      <ul>
        {config.category_localizations.map((c) => (
          <li key={`${c.category_id}-${c.profile_id}`}>
            {config.categories.find((x) => x.id === c.category_id)?.slug} ·{" "}
            {config.profiles.find((p) => p.id === c.profile_id)?.language_code}{" "}
            · {c.display_name}
          </li>
        ))}
      </ul>
      <fieldset disabled={pending}>
        <legend>용어집 저장</legend>
        <form onSubmit={(e) => submit(e, "glossary")}>
          <label>
            언어·국가
            <select name="profile_id" required>
              {profileOptions}
            </select>
          </label>
          <label>
            원어
            <input name="source_term" required maxLength={200} />
          </label>
          <label>
            현지 용어
            <input name="localized_term" required maxLength={200} />
          </label>
          <label>원문 언어 <input name="source_language" defaultValue="en" maxLength={100} /></label>
          <label>공식 번역 근거 <input name="translation_source" maxLength={2000} /></label>
          <label><input name="official_translation" type="checkbox" /> 공식 번역</label>
          <label><input name="approved" type="checkbox" /> 검토 승인 (공식 번역과 출처 필요)</label>
          <label>
            설명
            <input name="notes" maxLength={1000} />
          </label>
          <button>용어 저장</button>
        </form>
      </fieldset>
      <ul>
        {config.glossary.map((g) => (
          <li key={g.id}>
            {config.profiles.find((p) => p.id === g.profile_id)?.language_code}:{" "}
            {g.source_term} → {g.localized_term} · {g.approved ? "승인된 공식 번역" : "미승인·생성에 미사용"}
          </li>
        ))}
      </ul>
      <h2>언어·국가별 검색 성과</h2>
      {config.performance.length ? (
        <ul>
          {config.performance.map((p) => (
            <li key={`${p.language_code}-${p.country}`}>
              {p.language_code} / {p.country}: 클릭 {p.clicks}, 노출{" "}
              {p.impressions}
            </li>
          ))}
        </ul>
      ) : (
        <p>수집된 데이터가 없습니다. Search Console 연동은 후속 단계입니다.</p>
      )}
    </>
  );
}
