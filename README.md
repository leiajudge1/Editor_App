# Editor analytics — serverless web app (marimo + GitHub Pages)

A browser-based analytics dashboard for editors. Upload a **QTS report** and get
a full picture of the papers you've handled — computed entirely **in your
browser** via WebAssembly, so the uploaded file never leaves your machine.

## What it shows

- **Scientific spread** — an interactive **topic wheel** (each wedge a topic,
  filterable by subfield) plus field / subfield / topic tables.
- **Performance** — sortable tables ranked by **citations**, **FWCI** and
  **Altmetric**, each showing a **field-normalised percentile** ("Top 8%"), and a
  **citations × FWCI × Altmetric bubble chart** (bubble area = Altmetric, so
  outliers stand out; drag-select bubbles to list them with links).
- **PubPeer** — which of your papers have comments, with comment counts,
  **retraction / expression-of-concern flags**, and links.
- **Collaboration reach** — international vs. single-country, average countries
  per paper, top partner countries.
- **Geography** — the top-10 countries among your papers' authors.
- **Trends** — papers per month and median FWCI per month.
- **Who's citing you** (optional, see credits note) — journals, institutions,
  countries, and the top individual citing papers, with self-citation flags and a
  count of how many of your papers each citer references.
- **Download** — the full workbook (science tables + a per-paper sheet).

## Files

```
analytics_marimo.py                        <- the app (a marimo notebook)
.github/workflows/deploy-pages.yml         <- publishes it to GitHub Pages on push
altmetric-worker.js / wrangler.toml        <- optional Altmetric proxy (Cloudflare Worker)
WORKER_SETUP.md                            <- how to deploy that Worker
```

## Setup

1. Add `analytics_marimo.py` and `.github/workflows/deploy-pages.yml` to the repo.
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Push, or run the workflow from the **Actions** tab; the run prints the URL
   (e.g. `https://<you>.github.io/<repo>/`). Every push that changes the notebook
   rebuilds and republishes.

## Data sources & things to know

- **OpenAlex** (open, no key) powers spread, citations, FWCI, percentiles,
  geography, trends and the citation lookup. Requests use a contact email to sit
  in OpenAlex's "polite pool". OpenAlex now has a **daily free credit budget** —
  the core dashboard fits comfortably, but the **"who's citing you"** lookup makes
  a call per cited paper, so it's **opt-in** (a button) to avoid burning credits;
  the budget resets at midnight UTC.
- **Altmetric** — optional; needs the small Cloudflare Worker in `WORKER_SETUP.md`
  (it holds the Explorer key server-side) and its URL pasted into `WORKER_URL` near
  the top of the notebook. Without it, the Altmetric column is blank.
- **PubPeer** — called **directly from the browser**. This works from a normal
  (residential) connection but is blocked on some corporate networks (incl. the
  SN network), where that section will say it wasn't reachable. Nothing to fix —
  run it from another connection to see the data. It needs no key.

## Editing / previewing

```
pip install marimo
marimo edit analytics_marimo.py                       # edit interactively
marimo export html-wasm analytics_marimo.py -o _site --mode run
python -m http.server --directory _site               # preview the browser build
```

**marimo gotchas** (if you edit it): imports that packages need go at the **top of
a cell** (not inside functions) so they're bundled; every variable may be defined
in **only one cell**; packages Pyodide doesn't ship (openpyxl, plotly) need an
explicit `micropip.install`; and long `await` loops need `asyncio.sleep(0)` to let
the progress bar repaint. Keep slow/optional fetches in their **own cell** so they
don't hold up the rest of the dashboard.
