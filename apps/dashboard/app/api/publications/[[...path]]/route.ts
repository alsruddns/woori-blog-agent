import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers, localRequest } from "../../../../lib/server";

async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  if (!localRequest(request, true)) return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  if (!process.env.ADMIN_TOKEN) return NextResponse.json({ error: "API unavailable" }, { status: 503 });
  const path = (await context.params).path ?? [];
  const route = path.join("/");
  const allowed = request.method === "GET" && route === ""
    ? true
    : request.method === "POST" && (route === "requests" || /^jobs\/[a-f0-9-]+\/simulate$/.test(route) || /^blogs\/[a-f0-9-]+\/sync-readonly$/.test(route))
      ? true
        : request.method === "POST" && route === "emergency-stop"
          ? true
          : request.method === "PUT" && (route === "mode-settings" || /^jobs\/[a-f0-9-]+\/schedule$/.test(route))
        ? true
        : request.method === "DELETE" && /^jobs\/[a-f0-9-]+\/schedule$/.test(route);
  if (!allowed) return NextResponse.json({ error: "Unsupported operation" }, { status: 404 });
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    if (body && Buffer.byteLength(body) > 10000) return NextResponse.json({ error: "Request too large" }, { status: 413 });
    const suffix = route ? `/${path.map(encodeURIComponent).join("/")}` : "";
    const response = await fetch(`${API_BASE}/admin/publications${suffix}${request.nextUrl.search}`, {
      method: request.method, headers: headers(), body, cache: "no-store", signal: AbortSignal.timeout(10000),
    });
    const data: unknown = await response.json();
    return NextResponse.json(data, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Local publication API unavailable" }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
