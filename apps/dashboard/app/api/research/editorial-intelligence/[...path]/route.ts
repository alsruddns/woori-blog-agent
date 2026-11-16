import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers, localRequest } from "../../../../../lib/server";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!localRequest(request, true)) return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  if (!process.env.ADMIN_TOKEN) return NextResponse.json({ error: "API unavailable" }, { status: 503 });
  const { path } = await context.params;
  const route = path.join("/");
  const allowed = request.method === "GET" ? /^(aliases|settings|topics|monitor|pipeline|versions\/[0-9a-f-]{36}|imports\/[0-9a-f-]{36}\/compare)$/.test(route)
    : request.method === "PUT" ? route === "settings"
    : request.method === "POST" && /^(aliases|assess-current|imports\/[0-9a-f-]{36}\/(evaluate|deep-review)|reports\/[0-9a-f-]{36}\/(suggestions|recheck))$/.test(route);
  if (!allowed) return NextResponse.json({ error: "Unsupported operation" }, { status: 404 });
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    if (body && Buffer.byteLength(body) > 20000) return NextResponse.json({ error: "Request too large" }, { status: 413 });
    const url = new URL(`${API_BASE}/admin/research/editorial-intelligence/${route}`);
    if (request.method === "GET") request.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v));
    const response = await fetch(url, { method: request.method, body, headers: headers(), cache: "no-store", signal: AbortSignal.timeout(route.endsWith("deep-review") ? 270000 : 20000) });
    return NextResponse.json(await response.json(), { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "편집 평가 API에 연결하지 못했습니다. 실행 결과를 새로 조회하세요." }, { status: 503 }); }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
