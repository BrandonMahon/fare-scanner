// Fare Board backend: serves docs/ as static assets and proxies a small,
// allowlisted slice of the GitHub API for the admin page, so no browser ever
// holds a GitHub token. The whole Worker sits behind Cloudflare Access; a
// request that Access did not authenticate has no ctx.access and is refused.
//
// Env: GITHUB_TOKEN (secret: fine-grained PAT, Contents + Actions read/write,
// this repo only), GITHUB_REPO ("owner/name"), GITHUB_BRANCH.

const FILES = new Set(["trips.json", "config.json", "docs/data/bookings.json"]);
const WORKFLOWS = new Set(["trips.yml", "scan.yml"]);

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);

    if (!ctx.access) return json({ error: "Sign-in required" }, 401);
    const who = await ctx.access.getIdentity().catch(() => null);

    try {
      const route = `${request.method} ${url.pathname}`;
      if (route === "GET /api/me") return json({ email: who?.email ?? null });
      if (route === "GET /api/file") return await getFile(env, url.searchParams.get("path"));
      if (route === "PUT /api/file") return await putFile(env, await request.json());
      if (route === "POST /api/dispatch") return await dispatch(env, await request.json());
      return json({ error: "Not found" }, 404);
    } catch (e) {
      return json({ error: String(e.message || e) }, 500);
    }
  },
};

async function getFile(env, path) {
  if (!FILES.has(path)) return json({ error: "Path not allowed" }, 400);
  const r = await gh(env, `/contents/${path}?ref=${env.GITHUB_BRANCH}`);
  if (!r.ok) return passError(r);
  const j = await r.json();
  return json({ data: JSON.parse(b64dec(j.content)), sha: j.sha });
}

async function putFile(env, body) {
  const { path, data, sha, message } = body || {};
  if (!FILES.has(path)) return json({ error: "Path not allowed" }, 400);
  if (typeof sha !== "string" || typeof message !== "string" || data === undefined)
    return json({ error: "Expected path, data, sha, message" }, 400);
  const r = await gh(env, `/contents/${path}`, {
    method: "PUT",
    body: JSON.stringify({
      message: message.slice(0, 200), branch: env.GITHUB_BRANCH, sha,
      content: b64enc(JSON.stringify(data, null, 2) + "\n"),
    }),
  });
  if (!r.ok) return passError(r);
  return json({ sha: (await r.json()).content.sha });
}

async function dispatch(env, body) {
  const { workflow, inputs } = body || {};
  if (!WORKFLOWS.has(workflow)) return json({ error: "Workflow not allowed" }, 400);
  const clean = {};
  for (const [k, v] of Object.entries(inputs || {})) clean[k] = String(v).slice(0, 500);
  const r = await gh(env, `/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    body: JSON.stringify({ ref: env.GITHUB_BRANCH, inputs: clean }),
  });
  if (r.status !== 204) return passError(r);
  return new Response(null, { status: 204 });
}

function gh(env, path, init = {}) {
  const headers = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "fare-board-worker",
  };
  if (env.GITHUB_TOKEN) headers["Authorization"] = `Bearer ${env.GITHUB_TOKEN}`;
  return fetch(`https://api.github.com/repos/${env.GITHUB_REPO}${path}`, { ...init, headers });
}

// Keep GitHub's status (409 conflict matters to the admin page) but not its body.
async function passError(r) {
  const detail = await r.text().catch(() => "");
  console.log("GitHub API error", r.status, detail.slice(0, 300));
  return json({ error: `GitHub HTTP ${r.status}` }, r.status);
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

const b64enc = s => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
const b64dec = s => new TextDecoder().decode(
  Uint8Array.from(atob(s.replace(/\n/g, "")), c => c.charCodeAt(0)));
