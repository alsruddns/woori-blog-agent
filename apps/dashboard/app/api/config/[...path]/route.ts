import { API_BASE } from "../../../../lib/server";
import { NextRequest, NextResponse } from "next/server";
const resources = new Set([
  "languages",
  "blogs",
  "profiles",
  "policies",
  "categories",
  "category-localizations",
  "glossary",
]);
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (
    !["127.0.0.1:3100", "localhost:3100"].includes(host ?? "") ||
    origin !== `http://${host}`
  ) {
    return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  }
  if (!request.headers.get("content-type")?.startsWith("application/json"))
    return NextResponse.json({ error: "JSON required" }, { status: 415 });
  const { path } = await context.params;
  if (
    !resources.has(path[0]) ||
    path.length > 2 ||
    (path.length === 2 && !["languages", "blogs"].includes(path[0]))
  )
    return NextResponse.json(
      { error: "Unknown configuration route" },
      { status: 404 },
    );
  if (!process.env.ADMIN_TOKEN)
    return NextResponse.json(
      { error: "Configuration unavailable" },
      { status: 503 },
    );
  try {
    const text = await request.text();
    if (Buffer.byteLength(text, "utf8") > 16384)
      return NextResponse.json({ error: "Request too large" }, { status: 413 });
    const response = await fetch(
      `${API_BASE}/admin/config/${path.map(encodeURIComponent).join("/")}`,
      {
        method: request.method,
        headers: {
          Authorization: `Bearer ${process.env.ADMIN_TOKEN}`,
          "Content-Type": "application/json",
        },
        body: text,
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!response.ok)
      return NextResponse.json(
        { error: "Configuration rejected" },
        { status: response.status },
      );
    return NextResponse.json({ saved: true }, { status: response.status });
  } catch {
    return NextResponse.json({ error: "API unavailable" }, { status: 503 });
  }
}
export const POST = proxy;
export const PATCH = proxy;
