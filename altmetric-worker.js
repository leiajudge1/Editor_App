// altmetric-worker.js
// A tiny Cloudflare Worker that holds your Altmetric Explorer key + secret and
// returns Attention Scores for a list of DOIs. The browser app calls THIS, never
// Altmetric directly — so the secret never reaches the browser, and CORS is
// handled here.
//
// Secrets (set with `wrangler secret put`): ALTMETRIC_KEY, ALTMETRIC_SECRET
// Var (in wrangler.toml):                    ALLOWED_ORIGIN  (your Pages URL)

const API = "https://www.altmetric.com/explorer/api";

// HMAC-SHA1 -> lowercase hex, matching Python's hmac.new(...).hexdigest()
async function hmacSha1Hex(secret, message) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-1" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Step 1: create an identifier list. NOTE the special signing for this endpoint:
// the digest is over the raw identifiers string, keyed by the secret with
// hyphens stripped.
async function createList(dois, key, secret) {
  const identifiers = dois.join("\n");
  const digest = await hmacSha1Hex(secret.replace(/-/g, ""), identifiers);
  const body = "key=" + encodeURIComponent(key) +
               "&digest=" + digest +
               "&identifiers=" + encodeURIComponent(identifiers);
  const r = await fetch(API + "/identifier_lists", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!r.ok) throw new Error("identifier_lists " + r.status + ": " + (await r.text()).slice(0, 200));
  const j = await r.json();
  return j.data.id;
}

// Step 2: page through research_outputs for that list. Standard signing here:
// digest over "identifier_list_id|<id>", secret used as-is.
async function fetchScores(listId, key, secret) {
  const digest = await hmacSha1Hex(secret, "identifier_list_id|" + listId);
  let url = API + "/research_outputs" +
            "?filter[identifier_list_id]=" + encodeURIComponent(listId) +
            "&key=" + encodeURIComponent(key) +
            "&digest=" + digest +
            "&page[size]=100";
  const scores = {};
  let guard = 0;
  while (url && guard++ < 50) {
    const r = await fetch(url);
    if (!r.ok) throw new Error("research_outputs " + r.status + ": " + (await r.text()).slice(0, 200));
    const j = await r.json();
    for (const item of (j.data || [])) {
      const attrs = item.attributes || {};
      const score = attrs["altmetric-score"];
      const dois = (attrs.identifiers || {}).dois || [];
      for (const d of dois) {
        scores[String(d).toLowerCase()] =
          (typeof score === "number") ? Math.round(score * 10) / 10 : null;
      }
    }
    url = (j.links && j.links.next) || null;
  }
  return scores;
}

function jsonResponse(obj, cors, status = 200) {
  return new Response(JSON.stringify(obj), {
    status, headers: { ...cors, "Content-Type": "application/json" },
  });
}

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (request.method !== "POST") {
      return jsonResponse({ error: "POST a JSON body: {\"dois\": [...]}" }, cors, 405);
    }
    try {
      const { dois } = await request.json();
      if (!Array.isArray(dois) || dois.length === 0) return jsonResponse({ scores: {} }, cors);
      const key = env.ALTMETRIC_KEY, secret = env.ALTMETRIC_SECRET;
      if (!key || !secret) {
        return jsonResponse({ error: "Worker is missing ALTMETRIC_KEY / ALTMETRIC_SECRET" }, cors, 500);
      }
      const listId = await createList(dois, key, secret);
      const scores = await fetchScores(listId, key, secret);
      return jsonResponse({ scores }, cors);
    } catch (e) {
      return jsonResponse({ error: String(e && e.message || e) }, cors, 500);
    }
  },
};
