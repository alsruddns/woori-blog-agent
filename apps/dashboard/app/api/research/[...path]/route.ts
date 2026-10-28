import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers, localRequest } from "../../../../lib/server";
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!localRequest(request, true)) return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  if (!process.env.ADMIN_TOKEN) return NextResponse.json({ error: "API unavailable" }, { status: 503 });
  const { path } = await context.params;
  const route = path.join("/");
  const allowed = request.method === "GET" ? (["state", "manuscripts", "trend-observations", "model-comparisons", "topics", "trends", "content-imports"].includes(route)
    || /^content-imports\/[0-9a-f-]{36}$/.test(route)
    || /^content-imports\/[0-9a-f-]{36}\/localizations$/.test(route)
    || /^manuscripts\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/.test(route)
    || /^localized-publications\/targets\/[0-9a-f-]{36}\/[0-9a-f-]{36}$/.test(route)
    || /^trend-observations\/[0-9a-f-]{36}$/.test(route)
    || /^model-comparisons\/[0-9a-f-]{36}$/.test(route)) : request.method === "POST"
    ? /^(versions\/[a-f0-9-]+\/validate|collections|keywords|sources|jobs|prompts|schedules|editorial-preview|sources\/[a-f0-9-]+\/reviews|jobs\/[a-f0-9-]+\/action|article-reviews|article-review-events|article-revisions|publication-approvals|localized-publications\/requests|localized-publications\/requests\/[0-9a-f-]{36}\/cancel|content-imports|content-imports\/[0-9a-f-]{36}\/(assessment|versions|reviews|localizations|mock-publications)|content-imports\/[0-9a-f-]{36}\/localizations\/[a-zA-Z-]+\/cancel|trends\/collect|topics\/build|topics\/scoring-configs|topics\/[a-f0-9-]+\/(assess|decisions|categories|sources|package)|grouping-proposals\/[a-f0-9-]+\/reviews|topic-sources\/[a-f0-9-]+\/independence-reviews)$/.test(route)
    : request.method === "PUT" && /^(controls|collections\/[a-f0-9-]+|keywords\/[a-f0-9-]+)$/.test(route);
  if (!allowed) return NextResponse.json({ error: "Unsupported operation" }, { status: 404 });
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    const bodyLimit = route === "article-revisions" || route === "editorial-preview" || route === "content-imports" || /^content-imports\/[0-9a-f-]{36}\/versions$/.test(route) ? 150000 : 20000;
    if (body && Buffer.byteLength(body) > bodyLimit) return NextResponse.json({ error: "Request too large" }, { status: 413 });
    const upstreamUrl = new URL(`${API_BASE}/admin/research/${path.map(encodeURIComponent).join("/")}`);
    if (request.method === "GET") request.nextUrl.searchParams.forEach((value, key) => upstreamUrl.searchParams.set(key, value));
    const response = await fetch(upstreamUrl, {
      method: request.method, headers: headers(), body, cache: "no-store", signal: AbortSignal.timeout(15000),
    });
    const data: unknown = await response.json();
    return NextResponse.json(data, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "API ??? ??????." }, { status: 503 }); }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
