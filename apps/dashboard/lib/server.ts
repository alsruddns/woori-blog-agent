import type { NextRequest } from "next/server";
export const API_BASE =
  process.env.WOORI_API_BASE_URL ?? "http://127.0.0.1:8100";
if (API_BASE !== "http://127.0.0.1:8100")
  throw new Error("Invalid local API configuration");
export function localRequest(request: NextRequest, allowGet = false) {
  const host = request.headers.get("host");
  if (!["127.0.0.1:3100", "localhost:3100"].includes(host ?? "")) return false;
  return (
    request.headers.get("origin") === `http://${host}` ||
    (allowGet &&
      request.method === "GET" &&
      request.headers.get("sec-fetch-site") === "same-origin")
  );
}
export function headers() {
  return {
    Authorization: `Bearer ${process.env.ADMIN_TOKEN ?? ""}`,
    "Content-Type": "application/json",
  };
}
