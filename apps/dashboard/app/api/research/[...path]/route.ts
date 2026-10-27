import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers, localRequest } from "../../../../lib/server";
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!localRequest(request, true)) return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  if (!process.env.ADMIN_TOKEN) return NextResponse.json({ error: "API unavailable" }, { status: 503 });
  const { path } = await context.params;
  const route = path.join("/");
  const allowed = request.method === "GET" ? ["state", "local-ai"].includes(route) : request.method === "POST"
    ? /^(versions\/[a-f0-9-]+\/validate|collections|keywords|sources|jobs|prompts|schedules|sources\/[a-f0-9-]+\/reviews|jobs\/[a-f0-9-]+\/action|article-reviews|article-review-events|article-revisions)$/.test(route)
    : request.method === "PUT" && /^(controls|collections\/[a-f0-9-]+|keywords\/[a-f0-9-]+|settings\/[a-f0-9-]+)$/.test(route);
  if (!allowed) return NextResponse.json({ error: "Unsupported operation" }, { status: 404 });
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    const bodyLimit = route === "article-revisions" ? 60000 : 20000;
    if (body && Buffer.byteLength(body) > bodyLimit) return NextResponse.json({ error: "Request too large" }, { status: 413 });
    const response = await fetch(`${API_BASE}/admin/research/${path.map(encodeURIComponent).join("/")}`, {
      method: request.method, headers: headers(), body, cache: "no-store", signal: AbortSignal.timeout(15000),
    });
    const data: unknown = await response.json();
    return NextResponse.json(data, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "API ??? ??????." }, { status: 503 }); }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
