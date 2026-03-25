/**
 * Compliance Intelligence — Anthropic API proxy worker
 *
 * Proxies requests from the static GitHub Pages site to Anthropic,
 * keeping the API key server-side. Only accepts requests from the
 * allowed origin (GitHub Pages domain).
 *
 * Deploy:  wrangler deploy
 * Secret:  wrangler secret put ANTHROPIC_API_KEY
 */

const ALLOWED_ORIGIN = "https://ryan-jenkinson.github.io";

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const hdrs = corsHeaders(origin);

    // CORS preflight — always respond so browser doesn't see a network error
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: hdrs });
    }

    // Restrict to allowed origin
    if (origin !== ALLOWED_ORIGIN) {
      return new Response(JSON.stringify({ error: "Forbidden" }), {
        status: 403,
        headers: { ...hdrs, "Content-Type": "application/json" },
      });
    }

    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed" }), {
        status: 405,
        headers: { ...hdrs, "Content-Type": "application/json" },
      });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response(JSON.stringify({ error: "Invalid JSON" }), {
        status: 400,
        headers: { ...hdrs, "Content-Type": "application/json" },
      });
    }

    // Only allow haiku model to cap costs
    if (body.model && !body.model.startsWith("claude-haiku")) {
      body.model = "claude-haiku-4-5-20251001";
    }
    if (!body.max_tokens || body.max_tokens > 2000) {
      body.max_tokens = 1400;
    }

    const response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    return new Response(JSON.stringify(data), {
      status: response.status,
      headers: { ...hdrs, "Content-Type": "application/json" },
    });
  },
};
