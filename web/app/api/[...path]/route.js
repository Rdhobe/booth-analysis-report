import { NextResponse } from "next/server";

// Catch-all proxy: /api/overview?... -> FastAPI /api/overview?...
// Attaches X-API-Key server-side so the key never reaches the browser.
export async function GET(req, { params }) {
  const base = process.env.UPBI_API_BASE || "http://127.0.0.1:8000";
  const qs = new URL(req.url).search || "";
  const url = `${base}/api/${(params.path || []).join("/")}${qs}`;
  const key = process.env.UPBI_API_KEY || "";
  let r;
  try {
    r = await fetch(url, {
      headers: key ? { "x-api-key": key } : {},
      cache: "no-store",
    });
  } catch (e) {
    return NextResponse.json(
      { detail: `upstream unreachable: ${url} (${e.message})` },
      { status: 502 }
    );
  }
  const body = await r.text();
  return new NextResponse(body, {
    status: r.status,
    headers: {
      "content-type":
        r.headers.get("content-type") || "application/json",
    },
  });
}
