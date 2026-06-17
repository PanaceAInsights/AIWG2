#!/usr/bin/env python3
"""
Journal-club builder for the Prince of Wales Hospital (POWH) Department of
Dermatology journal club.

Reads the article data from journal-club/articles.json (produced either by
fetch_pubmed.py or by hand) and emits three self-contained artifacts:

  1. journal-club-derm-2025.html   - printable reading list / dossier (abstracts inline)
  2. journal-club-derm-2025.csv    - one row per paper incl. abstract (Excel/EndNote-friendly)
  3. journal-club-dashboard.html   - interactive dashboard: search, filter, per-paper cards

Presentation metadata (journal full names, scope labels, section order, the
explanatory callouts) lives in JOURNAL_META below; the article records come
from articles.json. Update JOURNAL_META only when the scope changes.

Run:  python3 journal-club/generate_report.py
"""

import os, re, csv, json, html, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

with open(os.path.join(HERE, "articles.json"), encoding="utf-8") as fh:
    _DATA = json.load(fh)
ARTICLES = _DATA["articles"]
GENERATED = _DATA.get("generated", "")
SOURCE = _DATA.get("source", "PubMed/NCBI (MEDLINE)")

# Output filenames (overridden by --site to build a standalone Pages bundle
# whose home page is index.html).
DASH_FILE = "journal-club-dashboard.html"
LIST_FILE = "journal-club-derm-2025.html"
CSV_FILE = "journal-club-derm-2025.csv"

# Presentation metadata. `sections` fixes the order papers are grouped in the
# reading list; any section label used in articles.json must appear here.
JOURNAL_ORDER = ["JAAD", "AJD", "BJD"]
JOURNAL_META = {
    "JAAD": {
        "full": "Journal of the American Academy of Dermatology",
        "scope": "April–May 2025 · Vol 92, Issues 4 (Apr) & 5 (May) · scope: CME / original / review",
        "callout": '<div class="callout">CME designation is inferred from JAAD\'s multi-part review series (Sunscreens I/II, Psoriatic arthritis I/II); PubMed carries no explicit "CME" tag, so confirm against the issue contents page. ≈149 research letters, correspondence, case reports, editorials and errata in these two issues fall outside the requested CME/original/review scope and are not listed.</div>',
        "sections": ["CME & Review articles", "Original articles"],
    },
    "AJD": {
        "full": "Australasian Journal of Dermatology",
        "scope": "May 2025 · Vol 66, Issue 3 (cover date May 2025) · scope: complete issue",
        "callout": "",
        "sections": ["Reviews, systematic reviews & viewpoints",
                     "Original & research articles",
                     "Case reports & case series",
                     "Letters / correspondence"],
    },
    "BJD": {
        "full": "British Journal of Dermatology",
        "scope": "Review articles · February–March 2025 · Vol 192, Issues 2 (Feb) & 3 (Mar), incl. adjacent",
        "callout": '<div class="callout">The <b>February issue (192/2) contained no review-type articles</b> (verified at issue level). The March issue (192/3) had the two reviews below; reviews from the February HS-themed supplement (192/S1) and the April issue (192/4) that appeared online during Feb–Mar are included here at your request.</div>',
        "sections": ["Reviews — March issue (192/3)",
                     "Reviews — February HS supplement (192/S1)",
                     "Reviews — April issue (192/4), online in Feb–Mar"],
    },
}

# -------------------------------------------------------------- helpers ------
def U(s):
    """Decode any leftover HTML numeric entities to real Unicode (idempotent)."""
    return html.unescape(s or "")

def coarse_type(badge):
    b = badge.lower()
    if "cme" in b: return "CME"
    if "guideline" in b or "consensus" in b: return "Guideline / Consensus"
    if "systematic" in b or "meta" in b: return "Systematic review / Meta-analysis"
    if "review" in b or "viewpoint" in b: return "Review"
    if "case" in b: return "Case report"
    if "letter" in b: return "Letter"
    if "short" in b: return "Short report"
    return "Original"

def badge_class(badge):
    b = badge.lower()
    if "cme" in b: return "b-cme"
    if "guideline" in b or "consensus" in b: return "b-guide"
    if "systematic" in b or "meta" in b: return "b-meta"
    if "review" in b or "viewpoint" in b: return "b-review"
    if "case" in b: return "b-case"
    if "letter" in b: return "b-letter"
    if "short" in b: return "b-short"
    return "b-orig"

CITE_RE = re.compile(r"^(.*?)\.\s*(\d{4});([^(]+)\(([^)]*)\):(.*)$")

def parse_cite(cite):
    m = CITE_RE.match(cite)
    if not m:
        return ("", "", "", "", "")
    return tuple(x.strip() for x in m.groups())  # journal, year, vol, issue, pages

def build_records():
    recs = []
    for a in ARTICLES:
        jshort = a["journal"]
        meta = JOURNAL_META.get(jshort, {"full": jshort})
        _jn, year, vol, issue, pages = parse_cite(a["cite"])
        recs.append({
            "journal": jshort, "journalFull": meta["full"], "section": a["section"],
            "type": coarse_type(a["badge"]), "badge": a["badge"],
            "authors": U(a["authors"]), "title": U(a["title"]),
            "cite": a["cite"], "year": year, "volume": vol, "issue": issue, "pages": pages,
            "doi": a["doi"], "doiUrl": f"https://doi.org/{a['doi']}",
            "pmid": a["pmid"], "pubmedUrl": f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/",
            "abstract": U(a.get("abstract", "")),
        })
    return recs

RECORDS = build_records()

# ------------------------------------------------------------- shared CSS ----
PALETTE = """
:root{--bg:#fafafa;--surface:#fff;--surface2:#f4f4f5;--border:#e4e4e7;--text:#18181b;--text2:#52525b;--text3:#71717a;--accent:#0f766e;--accent-bg:#ccfbf1}
@media(prefers-color-scheme:dark){:root{--bg:#09090b;--surface:#18181b;--surface2:#27272a;--border:#27272a;--text:#fafafa;--text2:#a1a1aa;--text3:#71717a;--accent:#2dd4bf;--accent-bg:#134e4a}}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);line-height:1.55;font-size:16px}
a{color:var(--accent)}
.badge{display:inline-block;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;padding:2px 7px;border-radius:5px;margin-right:7px;vertical-align:1px}
.b-cme{background:#fef3c7;color:#b45309}.b-review{background:#ede9fe;color:#6d28d9}.b-meta{background:#dbeafe;color:#1d4ed8}
.b-guide{background:#dcfce7;color:#15803d}.b-orig{background:var(--accent-bg);color:var(--accent)}.b-case{background:#f4f4f5;color:#52525b}
.b-letter{background:#fee2e2;color:#b91c1c}.b-short{background:#f4f4f5;color:#71717a}
@media(prefers-color-scheme:dark){.b-cme{background:#422006;color:#fbbf24}.b-review{background:#2e1065;color:#a78bfa}.b-meta{background:#1e3a8a;color:#60a5fa}.b-guide{background:#14532d;color:#4ade80}.b-letter{background:#450a0a;color:#f87171}.b-case,.b-short{background:#27272a;color:#a1a1aa}}
"""

# ============================================================ 1) REPORT ======
def esc(s): return html.escape(s, quote=True)

def abstract_html(rec):
    ab = rec["abstract"]
    if not ab:
        return '<div class="abs none">No abstract in PubMed (case report / letter — see full text).</div>'
    paras = "".join(f"<p>{esc(p.strip())}</p>" for p in re.split(r"\n+", ab) if p.strip())
    return f'<div class="abs">{paras}</div>'

def report_item(rec):
    return f"""        <li class="art">
          <span class="badge {badge_class(rec['badge'])}">{esc(rec['badge'])}</span>
          <a class="title" href="{rec['doiUrl']}" target="_blank" rel="noopener">{esc(rec['title'])}</a>
          <div class="meta">{esc(rec['authors'])} &middot; <span class="cite">{esc(rec['cite'])}</span></div>
          {abstract_html(rec)}
          <div class="links"><a href="{rec['doiUrl']}" target="_blank" rel="noopener">DOI</a> &middot; <a href="{rec['pubmedUrl']}" target="_blank" rel="noopener">PubMed {rec['pmid']}</a></div>
        </li>"""

def build_report():
    by_section = {}
    for r in RECORDS:
        by_section.setdefault((r["journal"], r["section"]), []).append(r)
    counts = {j: sum(1 for r in RECORDS if r["journal"] == j) for j in JOURNAL_ORDER}

    sections_html = []
    for i, jshort in enumerate(JOURNAL_ORDER, 1):
        meta = JOURNAL_META[jshort]
        groups = []
        # preset section order, then any extra sections the data introduced
        extra = [s for (jj, s) in by_section if jj == jshort and s not in meta["sections"]]
        seen = set()
        extra = [s for s in extra if not (s in seen or seen.add(s))]
        for sec_label in meta["sections"] + extra:
            recs = by_section.get((jshort, sec_label), [])
            if not recs:
                continue
            lis = "\n".join(report_item(r) for r in recs)
            groups.append(
                f'      <h3 class="grp">{esc(sec_label)} <span class="gcount">({len(recs)})</span></h3>\n'
                f'      <ul class="arts">\n{lis}\n      </ul>')
        sections_html.append(
            f'  <section>\n    <h2>{i} · {esc(meta["full"])} ({jshort})</h2>\n'
            f'    <div class="scope">{esc(meta["scope"])}</div>\n'
            f'    {meta.get("callout", "")}\n' + "\n".join(groups) + "\n  </section>")

    css = PALETTE + """
.wrap{max-width:980px;margin:0 auto;padding:40px 20px}
h1{font-size:28px;font-weight:700;letter-spacing:-.4px;margin-bottom:4px}
.sub{color:var(--text2);font-size:15px}
.date{color:var(--text3);font-size:12.5px;font-family:ui-monospace,monospace;margin-top:10px}
.tools{margin:18px 0 4px;font-size:13.5px}.tools a{margin-right:14px}
.summary{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin:18px 0}
.summary h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--text3);margin-bottom:12px}
.sgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.scard{background:var(--surface2);border-radius:9px;padding:12px 14px}.scard .n{font-size:24px;font-weight:700;color:var(--accent)}.scard .l{font-size:12.5px;color:var(--text2);margin-top:2px}
section{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px 24px;margin-bottom:22px}
section>h2{font-size:20px;font-weight:700;margin-bottom:2px}section>.scope{color:var(--text2);font-size:13.5px;margin-bottom:6px}
.grp{font-size:14px;font-weight:700;color:var(--accent);margin:22px 0 8px;text-transform:uppercase;letter-spacing:.04em}.gcount{color:var(--text3);font-weight:500}
ul.arts{list-style:none}li.art{padding:14px 0;border-top:1px solid var(--border)}li.art:first-child{border-top:none}
.title{font-weight:600;color:var(--text);text-decoration:none;font-size:15.5px}.title:hover{color:var(--accent);text-decoration:underline}
.meta{color:var(--text2);font-size:13.5px;margin-top:3px}.cite{font-family:ui-monospace,monospace;font-size:12.5px}
.abs{margin:7px 0 2px;font-size:13.5px;color:var(--text2);background:var(--surface2);border-radius:8px;padding:10px 13px}
.abs p{margin-bottom:7px}.abs p:last-child{margin-bottom:0}.abs.none{font-style:italic;color:var(--text3)}
.links{font-size:12px;margin-top:6px}.links a{text-decoration:none}.links a:hover{text-decoration:underline}
.callout{background:var(--surface2);border-left:3px solid var(--accent);border-radius:6px;padding:11px 14px;font-size:13.5px;color:var(--text2);margin:8px 0}
footer{color:var(--text3);font-size:12.5px;line-height:1.7;margin-top:8px;padding:0 4px}footer code{font-family:ui-monospace,monospace;background:var(--surface2);padding:1px 5px;border-radius:4px}
@media print{.tools{display:none}section,.summary{break-inside:avoid}}
"""
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>POWH Dermatology Journal Club — Reading List</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div class="wrap">
  <header>
    <h1>Dermatology Journal Club — Reading List</h1>
    <div class="sub">Prince of Wales Hospital (POWH), Department of Dermatology</div>
    <div class="date">Compiled {GENERATED} · Source: {SOURCE} · {len(RECORDS)} articles, {sum(1 for r in RECORDS if r['abstract'])} with abstracts</div>
    <div class="tools">↪ <a href="{DASH_FILE}">Interactive dashboard</a> · <a href="{CSV_FILE}">Download CSV</a></div>
  </header>
  <div class="summary"><h2>At a glance</h2><div class="sgrid">
    <div class="scard"><div class="n">{counts.get('JAAD',0)}</div><div class="l">JAAD — CME/review + original</div></div>
    <div class="scard"><div class="n">{counts.get('AJD',0)}</div><div class="l">AJD — full May issue</div></div>
    <div class="scard"><div class="n">{counts.get('BJD',0)}</div><div class="l">BJD — reviews (Feb–Mar, incl. adjacent)</div></div>
    <div class="scard"><div class="n">{len(RECORDS)}</div><div class="l">Total papers</div></div>
  </div></div>
""" + "\n".join(sections_html) + f"""
  <footer>
    <p><b>Method.</b> Retrieved from {SOURCE} and scoped by <code>journal + volume + issue</code> (not raw publication-date ranges), because PubMed mixes online-first and print-issue dates. Issue→month mapping verified against PubMed citation strings.</p>
    <p><b>Attribution.</b> Bibliographic data © the respective publishers, indexed by the U.S. National Library of Medicine (PubMed). Every entry links to its DOI and PubMed record; always cite the primary source.</p>
    <p>Regenerate with <code>python3 journal-club/generate_report.py</code>.</p>
  </footer>
</div></body></html>"""

# ============================================================== 2) CSV =======
def build_csv(path):
    cols = ["Journal","Section","Category","Badge","Authors","Title","Citation",
            "Year","Volume","Issue","Pages","DOI","DOI_URL","PMID","PubMed_URL","Abstract"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in RECORDS:
            w.writerow([r["journal"], r["section"], r["type"], r["badge"],
                        r["authors"], r["title"], r["cite"], r["year"], r["volume"],
                        r["issue"], r["pages"], r["doi"], r["doiUrl"], r["pmid"],
                        r["pubmedUrl"], re.sub(r"\s*\n+\s*", "  ", r["abstract"])])

# ========================================================== 3) DASHBOARD =====
def build_dashboard():
    data_json = json.dumps(RECORDS, ensure_ascii=False).replace("</", "<\\/")
    n_abs = sum(1 for r in RECORDS if r["abstract"])
    css = PALETTE + """
body{padding:0}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 60px}
header h1{font-size:26px;font-weight:700;letter-spacing:-.3px}
header .sub{color:var(--text2);font-size:14.5px;margin-top:2px}
header .date{color:var(--text3);font-size:12px;font-family:ui-monospace,monospace;margin-top:8px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:20px 0}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.stat .n{font-size:22px;font-weight:700;color:var(--accent)}.stat .l{font-size:12px;color:var(--text2);margin-top:2px}
.controls{position:sticky;top:0;z-index:5;background:var(--bg);padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:18px}
#q{width:100%;padding:11px 14px;font-size:15px;border:1px solid var(--border);border-radius:9px;background:var(--surface);color:var(--text);font-family:inherit}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.chip{font-size:12.5px;font-weight:600;padding:5px 12px;border-radius:999px;border:1px solid var(--border);background:var(--surface);color:var(--text2);cursor:pointer;user-select:none}
.chip:hover{border-color:var(--accent)}.chip.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.rowlabel{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--text3);margin:10px 6px 0 2px;align-self:center}
#count{font-size:13px;color:var(--text3);margin:14px 2px 6px}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 17px;display:flex;flex-direction:column}
.card .jtag{font-size:11px;font-weight:700;color:var(--text3);letter-spacing:.04em}
.card .title{font-weight:600;font-size:15px;margin:5px 0 0;color:var(--text);text-decoration:none;line-height:1.35}
.card .title:hover{color:var(--accent)}
.card .meta{font-size:12.5px;color:var(--text2);margin-top:6px}
.card .cite{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--text3);margin-top:3px}
.card .abs{font-size:13px;color:var(--text2);margin-top:9px;overflow:hidden;transition:max-height .2s}
.card .abs.clamp{display:-webkit-box;-webkit-line-clamp:5;-webkit-box-orient:vertical}
.card .abs.none{font-style:italic;color:var(--text3)}
.more{font-size:12px;color:var(--accent);cursor:pointer;margin-top:6px;font-weight:600;user-select:none;align-self:flex-start;background:none;border:none;padding:0;font-family:inherit}
.card .links{font-size:12px;margin-top:auto;padding-top:10px}.card .links a{text-decoration:none;margin-right:12px}
.empty{color:var(--text3);padding:40px 0;text-align:center}
footer{color:var(--text3);font-size:12px;line-height:1.7;margin-top:30px}footer code{font-family:ui-monospace,monospace;background:var(--surface2);padding:1px 5px;border-radius:4px}
"""
    js = r"""
const DATA = __DATA__;
const grid=document.getElementById('grid'), count=document.getElementById('count');
let state={journal:'All',type:'All',q:''};

function stats(){
  const by=k=>DATA.reduce((m,r)=>(m[r[k]]=(m[r[k]]||0)+1,m),{});
  const j=by('journal'); const el=document.getElementById('stats');
  const items=[['Total',DATA.length],['JAAD',j.JAAD||0],['AJD',j.AJD||0],['BJD',j.BJD||0],
    ['With abstract',DATA.filter(r=>r.abstract).length]];
  el.innerHTML=items.map(([l,n])=>`<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
}
function chips(){
  const journals=['All',...new Set(DATA.map(r=>r.journal))];
  const types=['All',...new Set(DATA.map(r=>r.type))];
  document.getElementById('jchips').innerHTML='<span class="rowlabel">Journal</span>'+
    journals.map(j=>`<span class="chip${j===state.journal?' on':''}" data-k="journal" data-v="${j}">${j}</span>`).join('');
  document.getElementById('tchips').innerHTML='<span class="rowlabel">Type</span>'+
    types.map(t=>`<span class="chip${t===state.type?' on':''}" data-k="type" data-v="${t}">${t}</span>`).join('');
  document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{state[c.dataset.k]=c.dataset.v;chips();render();});
}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function card(r){
  const ab=r.abstract
    ? `<div class="abs clamp">${esc(r.abstract)}</div><button class="more">▾ more</button>`
    : `<div class="abs none">No abstract (case report / letter).</div>`;
  return `<div class="card">
    <div class="jtag">${r.journal} · <span class="badge ${badgeClass(r.badge)}">${esc(r.badge)}</span></div>
    <a class="title" href="${r.doiUrl}" target="_blank" rel="noopener">${esc(r.title)}</a>
    <div class="meta">${esc(r.authors)}</div>
    <div class="cite">${esc(r.cite)}</div>
    ${ab}
    <div class="links"><a href="${r.doiUrl}" target="_blank" rel="noopener">DOI</a><a href="${r.pubmedUrl}" target="_blank" rel="noopener">PubMed ${r.pmid}</a></div>
  </div>`;
}
function badgeClass(b){b=b.toLowerCase();
  if(b.includes('cme'))return'b-cme';
  if(b.includes('guideline')||b.includes('consensus'))return'b-guide';
  if(b.includes('systematic')||b.includes('meta'))return'b-meta';
  if(b.includes('review')||b.includes('viewpoint'))return'b-review';
  if(b.includes('case'))return'b-case';
  if(b.includes('letter'))return'b-letter';
  if(b.includes('short'))return'b-short';
  return'b-orig';}
function render(){
  const q=state.q.trim().toLowerCase();
  const rows=DATA.filter(r=>
    (state.journal==='All'||r.journal===state.journal)&&
    (state.type==='All'||r.type===state.type)&&
    (!q||(r.title+' '+r.authors+' '+r.abstract).toLowerCase().includes(q)));
  count.textContent=`Showing ${rows.length} of ${DATA.length} papers`;
  grid.innerHTML=rows.length?rows.map(card).join(''):'<div class="empty">No papers match these filters.</div>';
  document.querySelectorAll('.more').forEach(btn=>btn.onclick=()=>{
    const a=btn.previousElementSibling;a.classList.toggle('clamp');
    btn.textContent=a.classList.contains('clamp')?'▾ more':'▴ less';});
}
document.getElementById('q').addEventListener('input',e=>{state.q=e.target.value;render();});
stats();chips();render();
"""
    js = js.replace("__DATA__", data_json)
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>POWH Dermatology Journal Club — Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{css}</style></head><body><div class="wrap">
  <header>
    <h1>Dermatology Journal Club — Dashboard</h1>
    <div class="sub">POWH Dept of Dermatology · JAAD (Apr–May 2025) · AJD (May 2025) · BJD reviews (Feb–Mar 2025)</div>
    <div class="date">Compiled {GENERATED} · Source: {SOURCE} · {len(RECORDS)} papers · {n_abs} with abstracts · <a href="{LIST_FILE}">reading list</a> · <a href="{CSV_FILE}">CSV</a></div>
  </header>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <input id="q" type="search" placeholder="Search title, author or abstract…" autocomplete="off">
    <div class="chips" id="jchips"></div>
    <div class="chips" id="tchips"></div>
  </div>
  <div id="count"></div>
  <div id="grid"></div>
  <footer><p>Scoped by journal + volume + issue from {SOURCE}. Bibliographic data © the respective publishers (indexed by PubMed); cite the primary source. Regenerate with <code>python3 journal-club/generate_report.py</code>.</p></footer>
</div>
<script>{js}</script>
</body></html>"""

# ----------------------------------------------------------------- main ------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the journal-club dashboard, reading list and CSV.")
    ap.add_argument("--site", metavar="DIR",
                    help="build a standalone GitHub Pages bundle (dashboard as index.html, "
                         "plus reading-list.html and CSV) into DIR")
    args = ap.parse_args()

    if args.site:
        DASH_FILE, LIST_FILE = "index.html", "reading-list.html"
        outdir = args.site
        os.makedirs(outdir, exist_ok=True)
        open(os.path.join(outdir, ".nojekyll"), "w").close()
    else:
        outdir = ROOT

    with open(os.path.join(outdir, LIST_FILE), "w", encoding="utf-8") as f:
        f.write(build_report())
    build_csv(os.path.join(outdir, CSV_FILE))
    with open(os.path.join(outdir, DASH_FILE), "w", encoding="utf-8") as f:
        f.write(build_dashboard())
    n_abs = sum(1 for r in RECORDS if r["abstract"])
    print(f"{len(RECORDS)} papers · {n_abs} abstracts -> {outdir}")
    print(f"wrote: {DASH_FILE}, {LIST_FILE}, {CSV_FILE}" + (", .nojekyll" if args.site else ""))
