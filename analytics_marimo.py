import marimo

__generated_with = "0.9.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _():
    # Environment detection: browser (Pyodide/WASM) vs local Python.
    import sys
    IS_WASM = ("pyodide" in sys.modules) or sys.platform == "emscripten"
    return IS_WASM, sys


@app.cell
def _(mo):
    mo.md(
        """
        # Editor portfolio analytics

        Upload your **QTS report** (Excel) — the DOI column is read for you — and
        get your portfolio's scientific spread, geographic spread, and current
        standouts. Everything runs **in your browser**: your file never leaves
        your machine, and there are no accounts or keys.

        *Altmetric scores aren't included here (they need a private key); this
        view is powered entirely by the open OpenAlex database.*
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
    return BRAND, COUNTRY_NAMES, RECENT_DAYS, TOP_N, WHEEL_TOP_N


@app.cell
def _(COUNTRY_NAMES):
    import re
    import io
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
def _(IS_WASM):
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
    return (fetch_openalex,)


@app.cell
def _(RECENT_DAYS, TOP_N, WHEEL_TOP_N, country_name):
    # ── Analysis + rendering (pure, no network) ───────────────────────────────
    from collections import Counter
    import datetime as dt
    import io
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
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

    def highlights(records):
        today = dt.date.today()

        def recent(r):
            try:
                return (today - dt.date.fromisoformat(r["date"])).days <= RECENT_DAYS
            except (ValueError, TypeError):
                return False

        def fwci(r):
            return r["fwci"] if isinstance(r["fwci"], (int, float)) else -1

        rows = []
        for r in sorted([x for x in records if recent(x)], key=fwci, reverse=True)[:TOP_N]:
            rows.append({"Why": "Recent (<{}d)".format(RECENT_DAYS), "DOI": r["doi"],
                         "Title": r["title"], "Published": r["date"],
                         "Citations": r["citations"], "FWCI": r["fwci"]})
        for r in sorted(records, key=fwci, reverse=True)[:TOP_N]:
            if fwci(r) > 0:
                rows.append({"Why": "Top FWCI", "DOI": r["doi"], "Title": r["title"],
                             "Published": r["date"], "Citations": r["citations"],
                             "FWCI": r["fwci"]})
        return rows

    def wheel_png(records):
        tc = Counter(r["topic"] for r in records)
        tsub = {}
        for r in records:
            tsub.setdefault(r["topic"], r["subfield"])
        total = len(tc)
        selected = [t for t, _ in tc.most_common(WHEEL_TOP_N)]
        selected.sort(key=lambda t: (tsub.get(t, ""), -tc[t]))
        counts = [tc[t] for t in selected]
        groups = [tsub.get(t, "Other") for t in selected]
        uniq = list(dict.fromkeys(groups))
        pal = plt.get_cmap("tab20")
        gcol = {g: pal(i % 20) for i, g in enumerate(uniq)}
        colors = [gcol[g] for g in groups]
        if not selected:
            return None
        ang = np.linspace(0, 2 * np.pi, len(selected), endpoint=False)
        rmax = max(counts)
        fig = plt.figure(figsize=(8, 8))
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
        handles = [plt.Rectangle((0, 0), 1, 1, color=gcol[g]) for g in uniq]
        ax.legend(handles, uniq, loc="center left", bbox_to_anchor=(1.02, 0.5),
                  fontsize=7.5, frameon=False, title="Subfield",
                  ncol=2 if len(uniq) > 6 else 1)
        shown = "top {} of {}".format(len(selected), total) if total > len(selected) else "all {}".format(len(selected))
        ax.set_title("Portfolio by topic ({}), grouped by subfield".format(shown),
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
                 "Field", "Subfield", "Topic", "Countries"]
        for c, h in enumerate(heads, 1):
            wp.cell(row=1, column=c, value=h).font = Font(bold=True)
        for i, r in enumerate(records, start=2):
            for c, key in enumerate(
                    ["doi", "title", "date", "citations", "fwci", "field",
                     "subfield", "topic"], 1):
                wp.cell(row=i, column=c, value=r[key])
            wp.cell(row=i, column=9, value=", ".join(r["countries"]))
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    return build_xlsx, highlights, summarise, wheel_png


@app.cell
def _(mo):
    file = mo.ui.file(filetypes=[".xlsx"], label="Upload your QTS report (.xlsx)")
    run = mo.ui.run_button(label="Build my analytics")
    mo.vstack([file, run])
    return file, run


@app.cell
async def _(dois_from_xlsx_bytes, fetch_openalex, extract, file, mo, run):
    # Gate the heavy work behind the button + an uploaded file.
    import traceback
    mo.stop(not run.value, mo.md("*Upload your QTS report, then press **Build my analytics**.*"))
    mo.stop(not file.value, mo.md("⚠️ No file uploaded yet."))

    records = []
    _err = None
    try:
        _dois = dois_from_xlsx_bytes(file.contents())
        if not _dois:
            _err = "No DOIs found in that spreadsheet."
        else:
            with mo.status.progress_bar(total=len(_dois), title="Fetching from OpenAlex") as bar:
                for _d in _dois:
                    _data = await fetch_openalex(_d)
                    if _data:
                        records.append(extract(_d, _data))
                    bar.update()
    except Exception:
        _err = traceback.format_exc()

    (mo.md("### ⚠️ Error while fetching\n\n```\n{}\n```".format(_err)) if _err
     else mo.md("Fetched **{}** of {} papers.".format(len(records), len(_dois))))
    return (records,)


@app.cell
def _(build_xlsx, highlights, mo, records, summarise, wheel_png):
    mo.stop(not records, mo.md(""))
    import traceback
    try:
        _s = summarise(records)
        _png = wheel_png(records)
        _intl_pct = (_s["intl"] / _s["n"]) if _s["n"] else 0
        _summary = mo.md(
            "### {} papers · {}\n\n"
            "**{}** fields · **{}** subfields · **{}** topics · "
            "**{}** countries · **{:.0%}** international".format(
                _s["n"], _s["range"], len(_s["field"]), len(_s["subfield"]),
                len(_s["topic"]), len(_s["country"]), _intl_pct))
        _wheel = mo.image(_png, width=620) if _png else mo.md("*No topic data.*")
        _dl = mo.download(data=build_xlsx(records), filename="portfolio_analytics.xlsx",
                          label="Download full workbook (.xlsx)")
        _table = mo.ui.table(highlights(records), selection=None, label="Highlights")
        _out = mo.vstack([_summary, _wheel, _dl, mo.md("### Highlights"), _table])
    except Exception:
        _out = mo.md("### ⚠️ Error while building the report\n\n```\n{}\n```".format(
            traceback.format_exc()))
    _out
    return


if __name__ == "__main__":
    app.run()
