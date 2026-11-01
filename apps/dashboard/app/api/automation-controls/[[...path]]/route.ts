import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers, localRequest } from "../../../../lib/server";

async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  if (!localRequest(request, true)) return NextResponse.json({ error: "관리자 동일 출처 요청이 필요합니다." }, { status: 403 });
  if (!process.env.ADMIN_TOKEN) return NextResponse.json({ error: "API 인증 설정을 확인하세요." }, { status: 503 });
  const path = (await context.params).path ?? [];
  if (!(path.length === 0 && ["GET", "PUT"].includes(request.method)) && !(path.join("/") === "verify-google-readonly" && request.method === "POST")) return NextResponse.json({ error: "지원하지 않는 요청입니다." }, { status: 404 });
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    if (body && Buffer.byteLength(body) > 10000) return NextResponse.json({ error: "요청이 너무 큽니다." }, { status: 413 });
    const response = await fetch(`${API_BASE}/admin/automation-controls${path.length ? `/${path[0]}` : ""}`, { method: request.method, headers: headers(), body, cache: "no-store", signal: AbortSignal.timeout(45000) });
    return NextResponse.json(await response.json(), { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "API 연결을 확인하세요. 설정은 변경된 것으로 간주하지 않습니다." }, { status: 503 }); }
}
export const GET = proxy;
export const PUT = proxy;
export const POST = proxy;
