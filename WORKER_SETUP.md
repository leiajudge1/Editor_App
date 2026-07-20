# Adding Altmetric scores to the app (Cloudflare Worker)

The browser app can't call Altmetric directly (the secret would be exposed, and
browsers block the cross-site call anyway). This small **Cloudflare Worker** sits
in between: it holds your Altmetric Explorer key + secret, does the signed
request, and returns just the scores. The key never reaches anyone's browser.

Free tier is 100,000 requests/day — you'll use a few hundred a month.

## Files

```
altmetric-worker.js   <- the Worker (holds no secrets itself)
wrangler.toml         <- its config
```

## One-time setup (~10 minutes)

1. **Create a free Cloudflare account** at cloudflare.com.

2. **Install Wrangler** (Cloudflare's deploy tool) — needs Node.js:
   ```
   npm install -g wrangler
   wrangler login
   ```

3. **Set your Pages origin** in `wrangler.toml` — change `ALLOWED_ORIGIN` to your
   real GitHub Pages URL (scheme + host, no trailing slash), e.g.
   `https://leiajudge1.github.io`. This is what limits who can call the Worker.

4. **Add your Altmetric secrets** (encrypted; they never go in any file):
   ```
   wrangler secret put ALTMETRIC_KEY
   wrangler secret put ALTMETRIC_SECRET
   ```
   Paste each value when prompted.

5. **Deploy:**
   ```
   wrangler deploy
   ```
   Wrangler prints the Worker's URL, like
   `https://altmetric-proxy.<your-subdomain>.workers.dev`.

## Test the Worker on its own (before touching the app)

This is the important step — confirm the Worker works in isolation, so any app
issue later is clearly separate. Use a DOI you know has attention:

```
curl -X POST https://altmetric-proxy.<your-subdomain>.workers.dev ^
  -H "Content-Type: application/json" ^
  -d "{\"dois\":[\"10.1038/s41467-025-56981-w\"]}"
```

(On Mac/Linux use `\` instead of `^` for line breaks.)

- **`{"scores":{"10.1038/...": 3.4}}`** → working. Note the number.
- **`{"error":"identifier_lists 401 ..."}`** → the key/secret are wrong or not a
  Details-Page-capable Explorer credential — re-check `wrangler secret put`.
- **`{"error":"research_outputs ..."}`** → the query step failed; send me the text.

## Connect it to the app

Open `analytics_marimo.py`, find this line near the top:

```python
WORKER_URL = ""
```

Paste your Worker URL between the quotes, commit, and push. That's it — the app
will now show an **Altmetric** column in the highlights and workbook, and a
"Top Altmetric" section. Leaving `WORKER_URL = ""` turns Altmetric back off.

## Good to know

- **Where the secret lives:** encrypted in Cloudflare, used only by the Worker.
  It's off your machine and out of the browser — but it *is* on Cloudflare (a
  third party). Same "org credential on someone else's platform" call as before,
  so worth a mention to whoever signs off. If it must stay in-house, the same
  Worker code can run on SN infrastructure instead.
- **Access control:** `ALLOWED_ORIGIN` stops other sites' browsers using your
  Worker. It's not bulletproof (a determined person could call it with a script),
  but for a low-volume internal tool it's a sensible guard. Ask me if you want a
  shared-token check added on top.
