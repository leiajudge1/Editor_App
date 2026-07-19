# Editor analytics — serverless web app (marimo + GitHub Pages)

A browser-based version of the portfolio analytics report. Editors open a link,
upload their QTS report, and get their topic wheel, spread, and highlights —
with **no server, no accounts, and no keys**. Everything runs in the browser
via WebAssembly, so the uploaded file never leaves the editor's machine.

Altmetric scores are **not** in this version (they need a private key, which
can't live safely in a browser app). It's powered entirely by OpenAlex. Your
scheduled GitHub Actions jobs still handle the Altmetric-based reports.

## Files

```
analytics_marimo.py                       <- the app (a marimo notebook, pure Python)
.github/workflows/deploy-pages.yml        <- publishes it to GitHub Pages on push
```

## One-time setup

1. Add both files to the repo (the workflow at `.github/workflows/deploy-pages.yml`).
2. Turn on Pages: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Push, or run the workflow from the **Actions** tab. When it finishes, the run
   shows the published URL (something like `https://<you>.github.io/<repo>/`).

After that, every push that changes `analytics_marimo.py` rebuilds and
republishes automatically.

## Editing the app

`analytics_marimo.py` is a normal marimo notebook. To change it interactively:

```
pip install marimo
marimo edit analytics_marimo.py
```

To preview the exact browser build locally before pushing (it must be served
over HTTP, not opened as a file):

```
marimo export html-wasm analytics_marimo.py -o _site --mode run
python -m http.server --directory _site
```

then open the printed URL.

## Good to know

- **First load is slowish.** The browser downloads the Python runtime (Pyodide)
  and the science packages the first time; it's cached afterwards.
- **Fetching runs on the editor's machine**, so ~150 papers takes a couple of
  minutes — there's a progress bar.
- **Private to your org?** A GitHub Pages site on a private repo is only served
  if your plan supports private Pages; otherwise the site is public (the *code*
  and *OpenAlex data* are public anyway, and no secrets are involved). If it must
  be access-restricted, host the same export behind SN's own login instead.
