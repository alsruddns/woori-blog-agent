import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers, localRequest } from "../../../../lib/server";

async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  if (!localRequest(request, true)) return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  if (!process.env.ADMIN_TOKEN) return NextResponse.json({ error: "API unavailable" }, { status: 503 });
  const path = (await context.params).path ?? [];
  const route = path.join("/");
  const allowed = request.method === "GET" && (route === "" || route === "worker-jobs" || route === "scheduled-auto-policy" || route === "scheduled-auto-first-post" || route === "scheduled-auto-state" || route === "trends-auto-policy" || route === "post-publication-reviews")
    ? true
    : request.method === "POST" && (route === "requests" || (route === "live-requests" || /^jobs\/[a-f0-9-]+\/sync-draft$/.test(route)) || route === "manual-live-requests" || /^jobs\/[a-f0-9-]+\/simulate$/.test(route) || /^blogs\/[a-f0-9-]+\/sync-readonly$/.test(route))
      ? true
        : request.method === "POST" && (route === "emergency-stop" || route === "scheduled-auto-policy" || route === "trends-auto-policy"
          || route === "scheduled-auto-first-post" || route === "scheduled-auto/verify-connections" || route === "trends-auto/verify-connections")
          ? true
          : request.method === "POST" && /^post-publication-reviews\/[a-f0-9-]+\/items$/.test(route)
            ? true
            : request.method === "POST" && /^post-publication-reviews\/[a-f0-9-]+\/items\/[a-f0-9-]+\/resolve$/.test(route)
              ? true
        : request.method === "PATCH" && (/^jobs\/[a-f0-9-]+\/draft-review$/.test(route) || /^post-publication-reviews\/[a-f0-9-]+$/.test(route))
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
export const PATCH = proxy;
export const DELETE = proxy;
