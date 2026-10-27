import { randomBytes } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { API_BASE, headers, localRequest } from "../../../../../lib/server";
export async function POST(request: NextRequest) {
  if (!localRequest(request))
    return NextResponse.json({ error: "Invalid origin" }, { status: 403 });
  if (!process.env.ADMIN_TOKEN)
    return NextResponse.json({ error: "API unavailable" }, { status: 503 });
  let permission: "read" | "write" = "read";
  try {
    const body = await request.json();
    if (body.permission !== undefined) {
      if (body.permission !== "read" && body.permission !== "write")
        return NextResponse.json({ error: "Invalid OAuth permission" }, { status: 400 });
      permission = body.permission;
    }
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }
  const binding = randomBytes(32).toString("base64url");
  try {
    const response = await fetch(`${API_BASE}/admin/blogger/oauth/start`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ binding, permission }),
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok)
      return NextResponse.json(
        { error: "OAuth 설정을 확인하세요." },
        { status: response.status },
      );
    const data = await response.json();
    if (
      !String(data.authorization_url).startsWith(
        "https://accounts.google.com/o/oauth2/v2/auth?",
      )
    )
      throw new Error("Invalid authorization endpoint");
    const result = NextResponse.json({
      authorization_url: data.authorization_url,
    });
    result.cookies.set("woori_oauth_binding", binding, {
      httpOnly: true,
      sameSite: "lax",
      secure: false,
      path: "/api/blogger/callback",
      maxAge: 600,
    });
    result.headers.set("Cache-Control", "no-store");
    return result;
  } catch {
    return NextResponse.json(
      { error: "OAuth 시작에 실패했습니다." },
      { status: 503 },
    );
  }
}
