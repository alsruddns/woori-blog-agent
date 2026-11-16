import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers } from "../../../../lib/server";
export async function GET(request: NextRequest) {
  let success = false;
  const binding = request.cookies.get("woori_oauth_binding")?.value;
  const state = request.nextUrl.searchParams.get("state");
  const host = request.headers.get("host");
  if (host === "127.0.0.1:3100" && binding && state) {
    try {
      const response = await fetch(`${API_BASE}/admin/blogger/oauth/callback`, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          binding,
          state,
          code: request.nextUrl.searchParams.get("code") ?? "",
          denied: request.nextUrl.searchParams.has("error"),
        }),
        cache: "no-store",
        signal: AbortSignal.timeout(20000),
      });
      success = response.ok;
    } catch {}
  }
  const result = NextResponse.redirect(
    `http://127.0.0.1:3100/blogger?oauth=${success ? "connected" : "failed"}`,
    303,
  );
  result.cookies.set("woori_oauth_binding", "", {
    httpOnly: true,
    sameSite: "lax",
    secure: false,
    path: "/api/blogger/callback",
    maxAge: 0,
  });
  result.headers.set("Cache-Control", "no-store");
  result.headers.set("Referrer-Policy", "no-referrer");
  return result;
}
