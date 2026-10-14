type Context = { params: Promise<{ path: string[] }> };

async function forward(request: Request, context: Context) {
  const { path } = await context.params;
  const base = (process.env.LEADOS_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  const target = `${base}/${path.map(encodeURIComponent).join("/")}${new URL(request.url).search}`;
  const headers = new Headers({ Accept: "application/json" });
  if (request.headers.has("content-type")) headers.set("content-type", request.headers.get("content-type")!);
  try {
    const response = await fetch(target, {
      method: request.method, headers, cache: "no-store",
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
      signal: AbortSignal.timeout(path.join("/") === "pipeline/discover/live" ? 480000 : 45000),
    });
    const outgoing = new Headers({ "Content-Type": response.headers.get("content-type") || "application/json", "Cache-Control": "no-store" });
    const sync = response.headers.get("x-leados-master-view");
    if (sync) outgoing.set("x-leados-master-view", sync);
    return new Response(response.body, { status: response.status, headers: outgoing });
  } catch {
    return Response.json({ detail: "Backend unavailable. Start both services with make dev, then retry." }, { status: 503 });
  }
}

export const GET = forward;
export const POST = forward;
