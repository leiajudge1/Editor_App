# Editor analytics — serverless web app (marimo + GitHub Pages)

A browser-based analytics dashboard. Editors open a link, upload their QTS
report, and get their **topic wheel**, scientific and geographic **spread**, and
**performance tables** ranked by citations, FWCI, and Altmetric — plus a
downloadable workbook. Everything runs in the browser via WebAssembly, so the
uploaded file never leaves the editor's machine.

Altmetric scores are optional: if you deploy the small Cloudflare Worker (see
`WORKER_SETUP.md`) and paste its URL into the notebook, the app adds an Altmetric
column and an Altmetric performance tab. Without it, the app still runs on
OpenAlex alone (that column is just blank).

## Files

```
analytics_marimo.py                       <- the app (a marimo notebook, pure Python)
.github/workflows/deploy-pages.yml        <- publishes it to GitHub Pages on push
altmetric-worker.js                       <- optional: Cloudflare Worker for Altmetric
WORKER_SETUP.md                           <- optional: how to deploy that Worker
```

## One-time setup

1. Add `analytics_marimo.py` and `.github/workflows/deploy-pages.yml` to the repo.
2. Turn on Pages: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Push, or run the workflow from the **Actions** tab. When it finishes, the run
   shows the published URL (something like `https://<you>.github.io/<repo>/`).

After that, every push that changes `analytics_marimo.py` rebuilds and
republishes automatically.

## Turning on Altmetric (optional)

1. Deploy the Worker following `WORKER_SETUP.md` (via the Cloudflare dashboard —
   no command line needed).
2. Paste the Worker's URL into the `WORKER_URL = ""` line near the top of
   `analytics_marimo.py`, commit, and push.

The secret stays inside the Worker; the app only ever sees scores.

## What the dashboard shows

- **Summary** — paper count, date range, and counts of fields / subfields /
  topics / countries, plus the international-collaboration rate.
- **Topic wheel** — a radial chart of the portfolio's topics, one wedge and one
  colour per topic, with a topic legend.
- **Performance** — three sortable, searchable tabs (Citations, FWCI, Altmetric),
  each ranking every paper by that metric; click any column header to re-sort.
- **Download** — the full workbook (science tables + a per-paper sheet).

## Editing the app

`analytics_marimo.py` is a normal marimo notebook:

```
pip install marimo
marimo edit analytics_marimo.py
```

To preview the exact browser build locally before pushing (serve over HTTP, not
file://):

```
marimo export html-wasm analytics_marimo.py -o _site --mode run
python -m http.server --directory _site
```

## Good to know

- **First load is slowish** — the browser downloads the Python runtime and the
  science packages once, then caches them.
- **Fetching runs on the editor's machine**, so ~150 papers takes a couple of
  minutes; there's a progress bar.
- **Marimo gotchas** (if you edit it): imports that packages need go at the *top*
  of a cell (not inside functions) so they're bundled; every variable may be
  defined in only one cell; and packages Pyodide doesn't ship (like openpyxl)
  need an explicit `micropip.install`.
- **Private to your org?** A public repo means a public site (the code and
  OpenAlex data are public anyway; no secrets are involved). If it must be
  access-restricted, host the same export behind SN's own login instead.
