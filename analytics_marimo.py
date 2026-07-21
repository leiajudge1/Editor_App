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
        inst_names = set()
        for a in data.get("authorships", []) or []:
            for c in a.get("countries", []) or []:
                if c:
                    codes.add(c.upper())
            for inst in a.get("institutions", []) or []:
                if inst.get("country_code"):
                    codes.add(inst["country_code"].upper())
                if inst.get("display_name"):
                    inst_names.add(inst["display_name"])
        cnp = data.get("citation_normalized_percentile") or {}
        pctl = cnp.get("value")
        return {
            "doi": doi,
            "oa_id": data.get("id") or "",
            "title": data.get("title") or "",
            "date": data.get("publication_date") or "",
            "citations": data.get("cited_by_count"),
            "fwci": data.get("fwci"),
            "percentile": pctl,  # 0-1; higher = cited more than that fraction of peers
            "top1": bool(cnp.get("is_in_top_1_percent")),
            "top10": bool(cnp.get("is_in_top_10_percent")),
            "domain": (pt.get("domain") or {}).get("display_name") or "Unclassified",
            "field": (pt.get("field") or {}).get("display_name") or "Unclassified",
            "subfield": (pt.get("subfield") or {}).get("display_name") or "Unclassified",
            "topic": pt.get("display_name") or "Unclassified",
            "countries": sorted(codes),
            "n_countries": len(codes),
            "inst_names": sorted(inst_names),
        }

    return clean_doi, country_name, dois_from_xlsx_bytes, extract, re


@app.cell
def _(IS_WASM, WORKER_URL):
    # ── Cross-environment OpenAlex fetch ──────────────────────────────────────
    # Browser: pyodide.http.pyfetch (async). Local: urllib (stdlib).
    async def fetch_openalex(doi, mailto=""):
        select = ("id,title,publication_date,cited_by_count,fwci,primary_topic,"
                  "authorships,type,citation_normalized_percentile")
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

    async def _oa_json(url):
        if IS_WASM:
            from pyodide.http import pyfetch
            resp = await pyfetch(url)
            return (await resp.json()) if resp.status == 200 else None
        import urllib.request
        import json
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    async def fetch_citing(items, self_insts, progress=None):
        # items: list of (oa_id, cited_by_count, your_paper_title).
        # Fetches the actual citing works per paper and aggregates journals,
        # institutions, countries, top individual citing papers, and which of
        # your papers each journal cited. Returns a dict.
        import asyncio
        from collections import Counter
        journals, institutions, countries = Counter(), Counter(), Counter()
        toppool = {}   # citing work id -> summary (deduped across your papers)
        base = "https://api.openalex.org/works"
        sel = "id,title,publication_date,cited_by_count,doi,primary_location,authorships"
        for _wid_url, _cby, _ptitle in items:
            wid = (_wid_url or "").rsplit("/", 1)[-1]
            if wid.startswith("W") and _cby:
                cursor, pages = "*", 0
                while cursor and pages < 5:
                    url = ("{}?filter=cites:{}&select={}&per-page=200&cursor={}"
                           .format(base, wid, sel, cursor))
                    data = None
                    for _try in range(3):
                        data = await _oa_json(url)
                        if data is not None:
                            break
                    if not data:
                        break
                    for cw in (data.get("results") or []):
                        src = (cw.get("primary_location") or {}).get("source") or {}
                        jn = src.get("display_name")
                        if jn:
                            journals[jn] += 1
                        seen_i, seen_c = set(), set()
                        for a in (cw.get("authorships") or []):
                            for ins in (a.get("institutions") or []):
                                inm = ins.get("display_name")
                                if inm and inm not in seen_i:
                                    seen_i.add(inm)
                                    institutions[inm] += 1
                            for cc in (a.get("countries") or []):
                                if cc and cc not in seen_c:
                                    seen_c.add(cc)
                                    countries[cc] += 1
                        cid = cw.get("id")
                        if cid:
                            e = toppool.get(cid)
                            if e is None:
                                e = {"title": (cw.get("title") or "")[:120],
                                     "journal": jn or "",
                                     "year": (cw.get("publication_date") or "")[:4],
                                     "citations": cw.get("cited_by_count") or 0,
                                     "url": (cw.get("doi") or cid), "yours": set()}
                                toppool[cid] = e
                            e["yours"].add(_ptitle)
                    cursor = (data.get("meta") or {}).get("next_cursor")
                    pages += 1
            if progress:
                progress()
            await asyncio.sleep(0)
        return {
            "journals": [(n, c, ("nature" in n.lower()))
                         for n, c in journals.most_common(100)],
            "institutions": [(n, c, (n in self_insts))
                             for n, c in institutions.most_common(100)],
            "countries": countries.most_common(100),
            "top_papers": [{"title": d["title"], "journal": d["journal"],
                            "year": d["year"], "citations": d["citations"],
                            "url": d["url"], "yours": len(d["yours"])}
                           for d in sorted(toppool.values(),
                                           key=lambda x: x["citations"], reverse=True)[:100]],
        }

    return fetch_altmetric, fetch_citing, fetch_openalex


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

    def pctl_label(r):
        v = r.get("percentile")
        if not isinstance(v, (int, float)):
            return ""
        top = (1.0 - v) * 100.0
        return "Top {:.0f}%".format(top) if top >= 1 else "Top 1%"

    def perf_rows(records, key):
        """All papers as rows, sorted by the given metric (desc).
        key is one of 'citations', 'fwci', 'altmetric'."""
        def val(r):
            v = r.get(key)
            return v if isinstance(v, (int, float)) else -1
        return [{"DOI": r["doi"], "Title": r["title"], "Published": r["date"],
                 "Citations": r["citations"], "FWCI": r["fwci"],
                 "Altmetric": r.get("altmetric"), "Field rank": pctl_label(r)}
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
                  bbox_to_anchor=(1.02, 0.5), fontsize=13, frameon=False,
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
        n = len(sizes)
        # True area-proportional sizing (like Excel): bubble AREA scales with the
        # Altmetric score, so outliers genuinely dominate. Plotly's sizemode="area"
        # + sizeref does exactly this. sizeref is set so the biggest score maps to
        # ~MAXPX pixels across; a size floor keeps zero/low papers just visible.
        MAXPX = 60.0
        FLOOR = 6.0
        smax = max(sizes) if sizes else 0
        sizeref = (2.0 * smax / (MAXPX ** 2)) if smax > 0 else 1.0
        raw = [(s if isinstance(s, (int, float)) and s > 0 else 0.0) for s in sizes]
        cdata = [[links[i], (sizes[i] if sizes[i] else "—")] for i in range(n)]
        fig = go.Figure(go.Scatter(
            x=xs, y=ys, mode="markers",
            marker=dict(size=raw, sizemode="area", sizeref=sizeref, sizemin=FLOOR,
                        color=ys, colorscale="Viridis", showscale=False,
                        line=dict(width=0.5, color="white"), opacity=0.7),
            customdata=cdata, text=texts,
            hovertemplate=("<b>%{text}</b><br>Citations: %{x}<br>FWCI: %{y:.2f}"
                           "<br>Altmetric: %{customdata[1]}<extra></extra>")))
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

    def collab_stats(records):
        n = len(records)
        solo = sum(1 for r in records if r["n_countries"] <= 1)
        avg = (sum(r["n_countries"] for r in records) / n) if n else 0
        partners = Counter(c for r in records if r["n_countries"] >= 2
                           for c in r["countries"])
        return {"solo": solo, "intl": n - solo, "avg": avg,
                "partners": [(country_name(c), v) for c, v in partners.most_common(8)]}

    def bench_summary(records):
        withp = sum(1 for r in records if isinstance(r.get("percentile"), (int, float)))
        return {"n_pct": withp,
                "top1": sum(1 for r in records if r.get("top1")),
                "top10": sum(1 for r in records if r.get("top10"))}

    def trend_fig(records):
        import statistics
        by_month = {}
        for r in records:
            m = (r["date"] or "")[:7]  # YYYY-MM
            if len(m) == 7 and m[:4].isdigit() and m[5:7].isdigit():
                by_month.setdefault(m, []).append(r)
        months = sorted(by_month)
        counts = [len(by_month[m]) for m in months]
        med = []
        for m in months:
            fs = [r["fwci"] for r in by_month[m] if isinstance(r["fwci"], (int, float))]
            med.append(round(statistics.median(fs), 2) if fs else None)
        fig = go.Figure()
        fig.add_bar(x=months, y=counts, name="Papers", marker_color="#B7A4CE")
        fig.add_scatter(x=months, y=med, name="Median FWCI", mode="lines+markers",
                        line=dict(color="#5B2C6F", width=3), yaxis="y2")
        fig.update_layout(height=380, template="simple_white",
                          xaxis=dict(title="Month", type="category"),
                          yaxis=dict(title="Papers"),
                          yaxis2=dict(title="Median FWCI", overlaying="y",
                                      side="right", showgrid=False),
                          legend=dict(orientation="h", y=1.12),
                          margin=dict(l=40, r=45, t=30, b=40))
        return fig

    return (bench_summary, bubble_fig, build_xlsx, collab_stats, country_fig,
            perf_rows, summarise, trend_fig, wheel_png)


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
async def _(fetch_citing, mo, records):
    citing = None
    if records:
        _items = [(r["oa_id"], r["citations"] or 0, r["title"] or r["doi"])
                  for r in records]
        _self_insts = set()
        for _r in records:
            for _nm in _r.get("inst_names", []):
                _self_insts.add(_nm)
        with mo.status.progress_bar(total=len(_items),
                                    title="Finding who cites your papers…") as _cbar:
            try:
                citing = await fetch_citing(_items, _self_insts,
                                            progress=lambda: _cbar.update())
            except Exception:
                citing = None
    return (citing,)


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
def _(bench_summary, bubble, build_xlsx, citing, collab_stats, country_fig,
      country_name, perf_rows, mo, records, subfield_dd, summarise, traceback,
      trend_fig, wheel_png):
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

        # Drag a box over bubbles -> persistent, clickable links below the chart.
        # (A single click usually won't register as a selection; dragging does.)
        _links_all = ["https://doi.org/" + r["doi"] for r in records]
        _sel_urls = []
        try:
            for _p in (bubble.value or []):
                _u = _p.get("customdata")
                if isinstance(_u, (list, tuple)):
                    _u = _u[0] if _u else None
                if not _u:
                    _idx = _p.get("pointNumber")
                    if _idx is None:
                        _idx = _p.get("pointIndex")
                    if _idx is None:
                        _idx = _p.get("point_number", _p.get("point_index"))
                    if isinstance(_idx, int) and 0 <= _idx < len(_links_all):
                        _u = _links_all[_idx]
                if _u and _u not in _sel_urls:
                    _sel_urls.append(_u)
        except Exception:
            pass
        if _sel_urls:
            _clicked = mo.md("**Selected papers ({}):**\n\n".format(len(_sel_urls))
                             + "\n".join("- [{}]({})".format(u, u) for u in _sel_urls))
        else:
            _clicked = mo.md("*Drag a box across bubbles to list them here as "
                             "clickable links — the hover box shows each paper.*")

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

        # Benchmarks (field/year-normalised percentiles)
        _bs = bench_summary(records)
        _bench = mo.md("**Field-normalised standing:** **{}** in the top 1% · "
                       "**{}** in the top 10%  *(of {} papers with percentile data)*".format(
                           _bs["top1"], _bs["top10"], _bs["n_pct"]))

        # Collaboration reach
        _cs = collab_stats(records)
        _partners = ", ".join("{} ({})".format(nm, ct) for nm, ct in _cs["partners"]) or "—"
        _collab = mo.md(
            "### Collaboration reach\n\n"
            "**{}** international · **{}** single-country · **{:.1f}** countries per "
            "paper on average\n\n**Most frequent partner countries:** {}".format(
                _cs["intl"], _cs["solo"], _cs["avg"], _partners))

        # Time trend
        _trend = mo.ui.plotly(trend_fig(records))

        # Who's citing you — journals, institutions, countries, top papers
        if citing:
            _jrows = [{"Journal": nm, "Citations": ct,
                       "Self (Nature)": "✓" if slf else ""}
                      for nm, ct, slf in citing["journals"]]
            _irows = [{"Institution": nm, "Citations": ct,
                       "Self-cite": "✓" if slf else ""}
                      for nm, ct, slf in citing["institutions"]]
            _crows = [{"Country": country_name(cc), "Citations": ct}
                      for cc, ct in citing["countries"]]
            _plink = {"Link": lambda v: mo.md("[open]({})".format(v))}
            _prows = [{"Title": p["title"], "Journal": p["journal"],
                       "Year": p["year"], "Citations": p["citations"],
                       "Your papers cited": p.get("yours", 1),
                       "Link": p["url"]} for p in citing["top_papers"]]
            _cite_view = mo.ui.tabs({
                "Journals": mo.ui.table(_jrows, selection=None, pagination=True, page_size=25),
                "Institutions": mo.ui.table(_irows, selection=None, pagination=True, page_size=25),
                "Countries": mo.ui.table(_crows, selection=None, pagination=True, page_size=25),
                "Top citing papers": mo.ui.table(_prows, selection=None, pagination=True,
                                                 page_size=25, format_mapping=_plink),
            })
        else:
            _cite_view = mo.md("*Citation data couldn't be retrieved this time "
                               "(OpenAlex may be busy) — try running again.*")

        _out = mo.vstack([
            _summary, _bench,
            mo.md("### Citations × FWCI × Altmetric"),
            mo.md("*Each bubble is a paper. Bubble area = Altmetric score, so "
                  "outliers stand out. Hover for details; **drag a box** over "
                  "bubbles to list them with links below.*"),
            bubble, _clicked,
            mo.md("### Over time"),
            mo.md("*Bars = papers per month; line = median FWCI per month.*"), _trend,
            mo.md("### Top 10 countries"), _country,
            _collab,
            mo.md("### Topic wheel"), subfield_dd, _wheel,
            mo.md("### Performance — ranked by each metric (DOIs are clickable)"), _tabs,
            mo.md("### Who's citing your portfolio"), _cite_view,
            _dl,
        ])
    except Exception:
        _out = mo.md("### ⚠️ Error while building the report\n\n```\n{}\n```".format(
            traceback.format_exc()))
    _out
    return


if __name__ == "__main__":
    app.run()
