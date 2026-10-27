import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers, localRequest } from "../../../../lib/server";
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  if (!localRequest(request, true))
    return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  if (!process.env.ADMIN_TOKEN)
    return NextResponse.json({ error: "API unavailable" }, { status: 503 });
  const { path } = await context.params;
  const route = path.join("/");
  const allowed =
    request.method === "GET"
      ? /^(status|content|blogs\/[a-f0-9-]+\/posts(\/[0-9]+)?)$/.test(route)
      : request.method === "PUT"
        ? /^limits\/[a-zA-Z0-9-]+$/.test(route)
        : request.method === "POST" &&
          /^(content|common-connection\/(verify|assign)|blogs\/[a-f0-9-]+\/(connect|disconnect|test)|oauth\/[a-f0-9-]+\/disconnect|blogs\/[a-f0-9-]+\/drafts\/preview|draft-previews\/[a-f0-9-]+\/confirm)$/.test(
            route,
          );
  if (!allowed)
    return NextResponse.json(
      { error: "Unsupported operation" },
      { status: 404 },
    );
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    if (body && Buffer.byteLength(body) > 60000)
      return NextResponse.json({ error: "Request too large" }, { status: 413 });
    const response = await fetch(
      `${API_BASE}/admin/blogger/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`,
      {
        method: request.method,
        headers: headers(),
        body,
        cache: "no-store",
        signal: AbortSignal.timeout(60000),
      },
    );
    const data = await response.json();
    if (!response.ok)
      return NextResponse.json(
        {
          error:
            typeof data.error === "string"
              ? data.error
              : "API 요청이 거절되었습니다.",
        },
        { status: response.status },
      );
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "API 연결에 실패했습니다." },
      { status: 503 },
    );
  }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
