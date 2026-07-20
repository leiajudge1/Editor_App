import marimo

__generated_with = "0.9.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
async def _():
    # Environment detection + shared stdlib imports (defined once).
    import sys
    import io
    import traceback
    IS_WASM = ("pyodide" in sys.modules) or sys.platform == "emscripten"
    # openpyxl isn't in Pyodide's preloaded set, so install it on demand in the
    # browser. Cells that import openpyxl depend on openpyxl_ready, so this runs
    # first.
    if IS_WASM:
        import micropip
        await micropip.install(["openpyxl", "plotly"])
    openpyxl_ready = True
    return IS_WASM, io, openpyxl_ready, traceback


@app.cell
def _(mo):
    mo.md(
        """
        # Editor portfolio analytics

        Upload your **QTS report** (Excel) — the DOI column is read for you — and
        get your portfolio's scientific spread, geographic spread, citation and
        attention performance, and current standouts. Everything runs **in your
        browser**: your file never leaves your machine.
        """
    )
    return


@app.cell
def _():
    # ── Config ────────────────────────────────────────────────────────────────
    BRAND = "5B2C6F"
    RECENT_DAYS = 60
    TOP_N = 12
    WHEEL_TOP_N = 32
    # Paste your deployed Cloudflare Worker URL here to add Altmetric scores.
    # Leave it empty ("") to run without Altmetric.
    WORKER_URL = "https://altmetric-proxy.leiajudge.workers.dev"
    COUNTRY_NAMES = {
        "US": "United States", "GB": "United Kingdom", "CN": "China",
        "DE": "Germany", "FR": "France", "JP": "Japan", "CA": "Canada",
        "AU": "Australia", "IT": "Italy", "ES": "Spain", "NL": "Netherlands",
        "CH": "Switzerland", "SE": "Sweden", "KR": "South Korea", "IN": "India",
        "BR": "Brazil", "BE": "Belgium", "DK": "Denmark", "AT": "Austria",
        "NO": "Norway", "FI": "Finland", "IL": "Israel", "IE": "Ireland",
        "SG": "Singapore", "PT": "Portugal", "PL": "Poland", "RU": "Russia",
        "MX": "Mexico", "ZA": "South Africa", "NZ": "New Zealand", "GR": "Greece",
        "CZ": "Czechia", "HU": "Hungary", "TR": "Turkey", "TW": "Taiwan",
        "HK": "Hong Kong", "SA": "Saudi Arabia", "AE": "United Arab Emirates",
        "AR": "Argentina", "CL": "Chile", "IR": "Iran", "TH": "Thailand",
        "MY": "Malaysia", "LU": "Luxembourg", "SI": "Slovenia", "EE": "Estonia",
    }
    return BRAND, COUNTRY_NAMES, RECENT_DAYS, TOP_N, WHEEL_TOP_N, WORKER_URL


@app.cell
def _(COUNTRY_NAMES, io, openpyxl_ready):
    import re
    from openpyxl import load_workbook

    def clean_doi(raw):
        s = str(raw).strip()
        s = re.sub(r"^https?://(dx\.)?doi\.org/", "", s, flags=re.I)
        s = re.sub(r"^doi:\s*", "", s, flags=re.I)
        return s.strip()

    def country_name(code):
        return COUNTRY_NAMES.get((code or "").upper(), code or "Unknown")

    def dois_from_xlsx_bytes(data):
        out = []
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            try:
                header = list(next(it))
            except StopIteration:
                continue
            idx = next((i for i, h in enumerate(header)
                        if isinstance(h, str) and h.strip().lower() == "doi"), None)
            rows = list(it)
            if idx is None:
                best, hits = None, 0
                for i in range(len(header)):
                    n = sum(1 for r in rows[:25] if i < len(r)
                            and isinstance(r[i], str) and re.search(r"10\.\d{4,}/", r[i]))
                    if n > hits:
                        best, hits = i, n
                idx = best
            if idx is None:
                continue
            for r in rows:
                if idx < len(r) and r[idx]:
                    out.append(clean_doi(r[idx]))
        # de-dupe, keep order, valid DOIs only
        seen, res = set(), []
        for d in out:
            k = d.lower()
            if d.lower().startswith("10.") and k not in seen:
                seen.add(k)
                res.append(d)
        return res

    def extract(doi, data):
        pt = data.get("primary_topic") or {}
        codes = set()
        for a in data.get("authorships", []) or []:
            for c in a.get("countries", []) or []:
                if c:
                    codes.add(c.upper())
            for inst in a.get("institutions", []) or []:
                if inst.get("country_code"):
                    codes.add(inst["country_code"].upper())
        return {
            "doi": doi,
            "title": data.get("title") or "",
            "date": data.get("publication_date") or "",
            "citations": data.get("cited_by_count"),
            "fwci": data.get("fwci"),
            "domain": (pt.get("domain") or {}).get("display_name") or "Unclassified",
            "field": (pt.get("field") or {}).get("display_name") or "Unclassified",
            "subfield": (pt.get("subfield") or {}).get("display_name") or "Unclassified",
            "topic": pt.get("display_name") or "Unclassified",
            "countries": sorted(codes),
            "n_countries": len(codes),
        }

    return clean_doi, country_name, dois_from_xlsx_bytes, extract, re


@app.cell
def _(IS_WASM, WORKER_URL):
    # ── Cross-environment OpenAlex fetch ──────────────────────────────────────
    # Browser: pyodide.http.pyfetch (async). Local: urllib (stdlib).
    async def fetch_openalex(doi, mailto=""):
        select = ("title,publication_date,cited_by_count,fwci,primary_topic,"
                  "authorships,type")
        url = "https://api.openalex.org/works/doi:{}?select={}".format(doi, select)
        if mailto:
            url += "&mailto=" + mailto
        if IS_WASM:
            from pyodide.http import pyfetch
            resp = await pyfetch(url)
            if resp.status == 404:
                return None
            if resp.status != 200:
                return None
            return await resp.json()
        else:
            import urllib.request
            import urllib.error
            import json
            try:
                with urllib.request.urlopen(url, timeout=15) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                raise

    async def fetch_altmetric(dois):
        # Ask the Cloudflare Worker for Altmetric scores. Returns {doi_lower: score}.
        # Empty dict if WORKER_URL isn't set or anything goes wrong (non-fatal).
        import json
        if not WORKER_URL:
            return {}
        payload = json.dumps({"dois": dois})
        if IS_WASM:
            from pyodide.http import pyfetch
            resp = await pyfetch(WORKER_URL, method="POST",
                                 headers={"Content-Type": "application/json"},
                                 body=payload)
            if resp.status != 200:
                return {}
            data = await resp.json()
        else:
            import urllib.request
            req = urllib.request.Request(
                WORKER_URL, data=payload.encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read().decode("utf-8"))
        return data.get("scores", {}) or {}

    return fetch_altmetric, fetch_openalex


@app.cell
def _(WHEEL_TOP_N, country_name, io, openpyxl_ready):
    # ── Analysis + rendering (pure, no network) ───────────────────────────────
    from collections import Counter
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import plotly.graph_objects as go
    from openpyxl import Workbook
    from openpyxl.styles import Font

    def summarise(records):
        n = len(records)
        field = Counter(r["field"] for r in records)
        subfield = Counter(r["subfield"] for r in records)
        topic = Counter(r["topic"] for r in records)
        domain = Counter(r["domain"] for r in records)
        country = Counter(c for r in records for c in r["countries"])
        intl = sum(1 for r in records if r["n_countries"] >= 2)
        dated = [r["date"] for r in records if r["date"]]
        return {
            "n": n, "field": field, "subfield": subfield, "topic": topic,
            "domain": domain, "country": country, "intl": intl,
            "range": ("{} to {}".format(min(dated), max(dated)) if dated else "-"),
        }

    def perf_rows(records, key):
        """All papers as rows, sorted by the given metric (desc).
        key is one of 'citations', 'fwci', 'altmetric'."""
        def val(r):
            v = r.get(key)
            return v if isinstance(v, (int, float)) else -1
        return [{"DOI": r["doi"], "Title": r["title"], "Published": r["date"],
                 "Citations": r["citations"], "FWCI": r["fwci"],
                 "Altmetric": r.get("altmetric")}
                for r in sorted(records, key=val, reverse=True)]

    def wheel_png(records, only_subfield=None):
        if only_subfield and only_subfield != "All":
            records = [r for r in records if r["subfield"] == only_subfield]
        tc = Counter(r["topic"] for r in records)
        total = len(tc)
        # Biggest topics first; each topic is its own wedge and its own colour.
        selected = [t for t, _ in tc.most_common(WHEEL_TOP_N)]
        counts = [tc[t] for t in selected]
        if not selected:
            return None
        # A distinct colour per topic: stitch together several qualitative maps.
        palette = []
        for cmap_name in ("tab20", "tab20b", "tab20c"):
            palette.extend(plt.get_cmap(cmap_name).colors)
        colors = [palette[i % len(palette)] for i in range(len(selected))]

        ang = np.linspace(0, 2 * np.pi, len(selected), endpoint=False)
        rmax = max(counts)
        fig = plt.figure(figsize=(9, 9))
        ax = fig.add_subplot(111, projection="polar")
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.bar(ang, counts, width=(2 * np.pi / len(selected)) * 0.95,
               color=colors, edgecolor="white", linewidth=1.0, alpha=0.9)
        ax.set_xticks([])
        ax.set_yticklabels([])
        ax.spines["polar"].set_visible(False)
        ax.set_ylim(0, rmax * 1.10)
        for a, c in zip(ang, counts):
            if c >= max(2, rmax * 0.25):
                ax.text(a, c / 2, str(c), ha="center", va="center",
                        fontsize=6.5, color="white", weight="bold")
        # Legend of topics (truncate long names so it stays readable).
        def _short(t):
            return t if len(t) <= 42 else t[:39] + "…"
        handles = [plt.Rectangle((0, 0), 1, 1, color=colors[i])
                   for i in range(len(selected))]
        ax.legend(handles, [_short(t) for t in selected], loc="center left",
                  bbox_to_anchor=(1.02, 0.5), fontsize=10.5, frameon=False,
                  title="Topic", ncol=2 if len(selected) > 16 else 1)
        shown = "top {} of {}".format(len(selected), total) if total > len(selected) else "all {}".format(len(selected))
        scope = "" if (not only_subfield or only_subfield == "All") else " — {}".format(only_subfield)
        ax.set_title("Portfolio by topic ({}){}".format(shown, scope),
                     fontsize=13, pad=24, weight="bold")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    def build_xlsx(records):
        s = summarise(records)
        wb = Workbook()
        ws = wb.active
        ws.title = "Science"
        for col, (name, counter) in enumerate(
                [("Field", s["field"]), ("Subfield", s["subfield"]),
                 ("Topic", s["topic"]), ("Country", s["country"])]):
            base = col * 3
            ws.cell(row=1, column=base + 1, value=name).font = Font(bold=True)
            ws.cell(row=1, column=base + 2, value="Papers").font = Font(bold=True)
            for i, (k, v) in enumerate(counter.most_common(), start=2):
                label = country_name(k) if name == "Country" else k
                ws.cell(row=i, column=base + 1, value=label)
                ws.cell(row=i, column=base + 2, value=v)
        wb.create_sheet("Papers")
        wp = wb["Papers"]
        heads = ["DOI", "Title", "Published", "Citations", "FWCI",
                 "Altmetric", "Field", "Subfield", "Topic", "Countries"]
        for c, h in enumerate(heads, 1):
            wp.cell(row=1, column=c, value=h).font = Font(bold=True)
        for i, r in enumerate(records, start=2):
            for c, key in enumerate(
                    ["doi", "title", "date", "citations", "fwci", "altmetric",
                     "field", "subfield", "topic"], 1):
                wp.cell(row=i, column=c, value=r.get(key))
            wp.cell(row=i, column=10, value=", ".join(r["countries"]))
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    def bubble_fig(records):
        # x = citations, y = FWCI, size = Altmetric (by rank, so it's dynamic).
        xs, ys, sizes, texts, links = [], [], [], [], []
        for r in records:
            xs.append(r["citations"] if isinstance(r["citations"], (int, float)) else 0)
            ys.append(r["fwci"] if isinstance(r["fwci"], (int, float)) else 0)
            a = r.get("altmetric")
            sizes.append(a if isinstance(a, (int, float)) else 0)
            texts.append((r["title"] or "")[:90])
            links.append("https://doi.org/" + r["doi"])
        # Rank-based sizing spreads bubbles evenly regardless of how skewed the
        # raw scores are, so differences are actually visible.
        n = len(sizes)
        if n and max(sizes) != min(sizes):
            order = sorted(range(n), key=lambda i: sizes[i])
            rank = [0] * n
            for pos, i in enumerate(order):
                rank[i] = pos
            msize = [7 + 40 * (rank[i] / (n - 1)) for i in range(n)]
        else:
            msize = [16] * n
        fig = go.Figure(go.Scatter(
            x=xs, y=ys, mode="markers",
            marker=dict(size=msize, color=ys, colorscale="Viridis", showscale=False,
                        line=dict(width=0.5, color="white"), opacity=0.75),
            customdata=links, text=texts,
            hovertemplate=("<b>%{text}</b><br>Citations: %{x}<br>FWCI: %{y:.2f}"
                           "<br>Altmetric size-ranked<extra></extra>")))
        fig.update_layout(xaxis_title="Citations", yaxis_title="FWCI",
                          height=520, template="simple_white", dragmode="select",
                          margin=dict(l=50, r=20, t=20, b=45))
        return fig

    def country_fig(records):
        cc = Counter(c for r in records for c in r["countries"])
        top = cc.most_common(10)[::-1]
        fig = go.Figure(go.Bar(
            x=[n for _, n in top], y=[country_name(c) for c, _ in top],
            orientation="h", marker_color="#5B2C6F",
            hovertemplate="%{y}: %{x} papers<extra></extra>"))
        fig.update_layout(height=380, template="simple_white",
                          xaxis_title="Papers", margin=dict(l=10, r=10, t=10, b=30))
        return fig

    return bubble_fig, build_xlsx, country_fig, perf_rows, summarise, wheel_png


@app.cell
def _(mo):
    file = mo.ui.file(filetypes=[".xlsx"], label="Upload your QTS report (.xlsx)")
    run = mo.ui.run_button(label="Build my analytics")
    mo.vstack([file, run])
    return file, run


@app.cell
async def _(dois_from_xlsx_bytes, fetch_altmetric, fetch_openalex, extract, file, mo, run, traceback, WORKER_URL):
    # Gate the heavy work behind the button + an uploaded file.
    import asyncio
    mo.stop(not run.value, mo.md("*Upload your QTS report, then press **Build my analytics**.*"))
    mo.stop(not file.value, mo.md("⚠️ No file uploaded yet."))

    records = []
    _err = None
    try:
        _dois = dois_from_xlsx_bytes(file.contents())
        if not _dois:
            _err = "No DOIs found in that spreadsheet."
        else:
            with mo.status.progress_bar(
                total=len(_dois), title="Fetching from OpenAlex",
                subtitle="First run downloads the Python packages — hang on a moment.",
            ) as bar:
                for _i, _d in enumerate(_dois):
                    _data = await fetch_openalex(_d)
                    if _data:
                        records.append(extract(_d, _data))
                    bar.update(subtitle="{} of {} papers".format(_i + 1, len(_dois)))
                    # Yield to the browser so the progress bar actually repaints.
                    await asyncio.sleep(0)
            # Optional Altmetric scores (only if a Worker URL is configured).
            if WORKER_URL and records:
                with mo.status.spinner(title="Fetching Altmetric scores…"):
                    try:
                        _scores = await fetch_altmetric([r["doi"] for r in records])
                    except Exception:
                        _scores = {}
                for r in records:
                    r["altmetric"] = _scores.get(r["doi"].lower())
    except Exception:
        _err = traceback.format_exc()

    (mo.md("### ⚠️ Error while fetching\n\n```\n{}\n```".format(_err)) if _err
     else mo.md("Fetched **{}** of {} papers.".format(len(records), len(_dois))))
    return (records,)


@app.cell
def _(bubble_fig, mo, records, summarise):
    # UI elements live in their own cell so their .value changes drive updates.
    mo.stop(not records, mo.md(""))
    _subs = sorted(summarise(records)["subfield"].keys())
    subfield_dd = mo.ui.dropdown(options=["All"] + _subs, value="All",
                                 label="Filter the topic wheel by subfield")
    bubble = mo.ui.plotly(bubble_fig(records))
    return bubble, subfield_dd


@app.cell
def _(bubble, build_xlsx, country_fig, perf_rows, mo, records, subfield_dd,
      summarise, traceback, wheel_png):
    mo.stop(not records, mo.md(""))
    try:
        _s = summarise(records)
        _intl_pct = (_s["intl"] / _s["n"]) if _s["n"] else 0
        _summary = mo.md(
            "### {} papers · {}\n\n"
            "**{}** fields · **{}** subfields · **{}** topics · "
            "**{}** countries · **{:.0%}** international".format(
                _s["n"], _s["range"], len(_s["field"]), len(_s["subfield"]),
                len(_s["topic"]), len(_s["country"]), _intl_pct))

        # Clicked bubble -> surface the paper's link (opens in a new tab).
        _clicked = mo.md("*Tip: hover a bubble for the paper; click one to get its link.*")
        try:
            _pts = bubble.value or []
            if _pts:
                _url = _pts[0].get("customdata")
                if isinstance(_url, (list, tuple)):
                    _url = _url[0]
                if _url:
                    _clicked = mo.md("**Selected paper:** [{}]({})".format(_url, _url))
        except Exception:
            pass

        _wheel = mo.image(wheel_png(records, subfield_dd.value), width=680)
        _country = mo.ui.plotly(country_fig(records))

        # DOIs render as clickable links (open the paper) but stay sortable.
        _fmt = {"DOI": lambda v: mo.md("[{}](https://doi.org/{})".format(v, v))}
        _tab = lambda key: mo.ui.table(perf_rows(records, key), selection=None,
                                       pagination=True, page_size=15, format_mapping=_fmt)
        _tabs = mo.ui.tabs({"Citations": _tab("citations"),
                            "FWCI": _tab("fwci"), "Altmetric": _tab("altmetric")})

        _dl = mo.download(data=build_xlsx(records),
                          filename="portfolio_analytics.xlsx",
                          label="Download full workbook (.xlsx)")

        _out = mo.vstack([
            _summary,
            mo.md("### Citations × FWCI × Altmetric"),
            mo.md("*Each bubble is a paper. Bubble size = Altmetric score.*"),
            bubble, _clicked,
            mo.md("### Top 10 countries"), _country,
            mo.md("### Topic wheel"), subfield_dd, _wheel,
            mo.md("### Performance — ranked by each metric (DOIs are clickable)"), _tabs,
            _dl,
        ])
    except Exception:
        _out = mo.md("### ⚠️ Error while building the report\n\n```\n{}\n```".format(
            traceback.format_exc()))
    _out
    return


if __name__ == "__main__":
    app.run()
