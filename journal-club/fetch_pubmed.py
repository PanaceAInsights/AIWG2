#!/usr/bin/env python3
"""
Standalone PubMed fetcher for the POWH dermatology journal-club toolkit.

Queries NCBI E-utilities (esearch + efetch) by journal + volume + issue,
classifies each paper by publication type, and writes articles.json — the data
file that generate_report.py turns into the reading list, CSV and dashboard.

  python3 journal-club/fetch_pubmed.py                 # fetch per scope.json -> articles.json
  python3 journal-club/fetch_pubmed.py --scope my.json --out articles.json
  python3 journal-club/fetch_pubmed.py --selftest      # offline: validate parser/classifier
  python3 journal-club/fetch_pubmed.py --dry-run       # query + classify, print, don't write

Dependencies: Python 3 standard library only (urllib, xml.etree). No pip installs.

NETWORK: needs outbound HTTPS to eutils.ncbi.nlm.nih.gov. In a locked-down
environment (e.g. Claude Code on the web with a restricted egress allowlist),
add that host to the network allowlist, or run this script on a normal machine.
Set NCBI_API_KEY (and optionally NCBI_EMAIL) in the environment to raise the
rate limit from 3 to 10 requests/sec.

scope.json format — a list under "queries", each one of:
  {"journal_short":"AJD", "term":"<PubMed query>", "mode":"issue",
   "sections":{"review":"...","original":"...","case":"...","letter":"..."}}
  {"journal_short":"JAAD","term":"<query>", "mode":"fixed",   "section":"...", "require_abstract":false}
  {"journal_short":"JAAD","term":"<query>", "mode":"original","section":"...", "min_abstract":400}
  {"journal_short":"BJD", "pmids":["...","..."], "mode":"fixed","section":"..."}   # explicit PMIDs
"""

import argparse, json, os, sys, time, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL, EMAIL, API_KEY = "powh-jc-fetch", os.environ.get("NCBI_EMAIL", ""), os.environ.get("NCBI_API_KEY", "")

# ------------------------------------------------------------- E-utilities ---
def _params(extra):
    p = {"tool": TOOL, **extra}
    if EMAIL: p["email"] = EMAIL
    if API_KEY: p["api_key"] = API_KEY
    return p

def _open(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": TOOL})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.read()
    except urllib.error.URLError as e:
        sys.exit(f"\nERROR reaching NCBI E-utilities: {e}\n"
                 f"If you are in a restricted environment, add 'eutils.ncbi.nlm.nih.gov' "
                 f"to the network egress allowlist, or run this on an unrestricted machine.\n")

def _sleep():
    time.sleep(0.11 if API_KEY else 0.34)

def esearch(term, retmax=400):
    q = urllib.parse.urlencode(_params({"db": "pubmed", "term": term, "retmode": "json", "retmax": retmax}))
    _sleep()
    res = json.loads(_open(f"{EUTILS}/esearch.fcgi?{q}"))
    return res.get("esearchresult", {}).get("idlist", [])

def efetch(pmids):
    out = []
    for i in range(0, len(pmids), 150):
        chunk = pmids[i:i + 150]
        data = urllib.parse.urlencode(_params({"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"})).encode()
        _sleep()
        out.extend(parse_articles(_open(f"{EUTILS}/efetch.fcgi", data=data)))
    return out

# --------------------------------------------------------------- XML parse ---
def _text(el):
    return "".join(el.itertext()).strip() if el is not None else ""

def parse_articles(xml_bytes):
    root = ET.fromstring(xml_bytes)
    recs = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//MedlineCitation/PMID") or ""
        title = _text(art.find(".//Article/ArticleTitle")).rstrip(".")
        # abstract (keep structured-section labels if present)
        parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            txt = _text(ab)
            if not txt:
                continue
            lab = ab.get("Label")
            parts.append(f"{lab}: {txt}" if lab and lab.upper() not in ("UNLABELLED", "UNASSIGNED") else txt)
        abstract = "\n\n".join(parts)
        # authors -> "First IN, et al."
        names = []
        for a in art.findall(".//Article/AuthorList/Author"):
            ln, ini = a.findtext("LastName"), a.findtext("Initials")
            if ln:
                names.append(f"{ln} {ini}".strip())
            elif a.findtext("CollectiveName"):
                names.append(a.findtext("CollectiveName"))
        if not names:
            authors = ""
        elif len(names) == 1:
            authors = names[0]
        elif len(names) == 2:
            authors = f"{names[0]}, {names[1]}"
        else:
            authors = f"{names[0]}, et al."
        # journal / citation bits
        iso = art.findtext(".//Article/Journal/ISOAbbreviation") or ""
        vol = art.findtext(".//JournalIssue/Volume") or ""
        issue = art.findtext(".//JournalIssue/Issue") or ""
        year = art.findtext(".//JournalIssue/PubDate/Year") or ""
        if not year:
            md = art.findtext(".//JournalIssue/PubDate/MedlineDate") or ""
            year = md[:4]
        pages = art.findtext(".//Pagination/MedlinePgn") or art.findtext(".//Pagination/StartPage") or ""
        doi = ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").strip()
        if not doi:
            for el in art.findall(".//ELocationID"):
                if el.get("EIdType") == "doi":
                    doi = (el.text or "").strip()
        pubtypes = [pt.text for pt in art.findall(".//PublicationTypeList/PublicationType") if pt.text]
        recs.append(dict(pmid=pmid, title=title, abstract=abstract, authors=authors,
                         iso=iso, volume=vol, issue=issue, year=year, pages=pages,
                         doi=doi, pubtypes=pubtypes))
    return recs

# --------------------------------------------------------------- classify ---
SKIP_PT = {"Published Erratum", "Retraction of Publication", "Retracted Publication"}

def badge_from_pubtypes(pts, has_abstract):
    s = set(pts)
    if "Meta-Analysis" in s and "Systematic Review" in s: return "Systematic review / Meta-analysis"
    if "Practice Guideline" in s or "Guideline" in s: return "Guideline"
    if "Consensus Development Conference" in s: return "Consensus"
    if "Meta-Analysis" in s: return "Meta-analysis"
    if "Systematic Review" in s: return "Systematic review"
    if "Review" in s: return "Review"
    if "Case Reports" in s: return "Case report"
    if "Letter" in s: return "Letter"
    if "Editorial" in s: return "Editorial"
    if "Randomized Controlled Trial" in s: return "Original (RCT)"
    return "Original" if has_abstract else "Short report"

def section_key(badge):
    b = badge.lower()
    if any(x in b for x in ("review", "guideline", "consensus", "meta", "viewpoint")): return "review"
    if "case" in b: return "case"
    if "letter" in b or "editorial" in b or "comment" in b: return "letter"
    return "original"

def cite_str(r):
    iss = f"({r['issue']})" if r["issue"] else ""
    return f"{r['iso']}. {r['year']};{r['volume']}{iss}:{r['pages']}"

def classify(r, q):
    """Return (section, badge) or None to drop the paper."""
    if SKIP_PT & set(r["pubtypes"]):
        return None
    has_abs = bool(r["abstract"])
    badge = badge_from_pubtypes(r["pubtypes"], has_abs)
    mode = q.get("mode", "fixed")
    if mode == "issue":
        return (q["sections"][section_key(badge)], badge)
    if mode == "original":
        if len(r["abstract"]) < q.get("min_abstract", 400):
            return None  # drop research letters / abstract-less items
        return (q["section"], "Original (RCT)" if "Randomized Controlled Trial" in r["pubtypes"] else "Original")
    # fixed
    if q.get("require_abstract") and not has_abs:
        return None
    return (q.get("section", "Articles"), q.get("badge") or badge)

# ----------------------------------------------------------------- driver ---
def run(scope, verbose=True):
    seen, articles = set(), []
    for q in scope["queries"]:
        pmids = q["pmids"] if "pmids" in q else esearch(q["term"])
        recs = efetch(pmids) if pmids else []
        kept = 0
        for r in recs:
            if r["pmid"] in seen:
                continue
            res = classify(r, q)
            if not res:
                continue
            section, badge = res
            seen.add(r["pmid"])
            articles.append(dict(journal=q["journal_short"], section=section, badge=badge,
                                 authors=r["authors"], title=r["title"], cite=cite_str(r),
                                 doi=r["doi"], pmid=r["pmid"], abstract=r["abstract"]))
            kept += 1
        if verbose:
            label = q.get("section") or q.get("journal_short")
            print(f"  [{q['journal_short']}] {len(pmids):>3} found -> {kept:>2} kept   ({label})")
    return articles

# --------------------------------------------------------------- self-test ---
SAMPLE_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle><MedlineCitation>
   <PMID>11111111</PMID>
   <Article>
     <Journal><ISOAbbreviation>Australas J Dermatol</ISOAbbreviation>
       <JournalIssue><Volume>66</Volume><Issue>3</Issue><PubDate><Year>2025</Year></PubDate></JournalIssue></Journal>
     <ArticleTitle>A clinical review of something important in skin of colour.</ArticleTitle>
     <Pagination><MedlinePgn>119-126</MedlinePgn></Pagination>
     <Abstract>
       <AbstractText Label="Background">Post-inflammatory change matters.</AbstractText>
       <AbstractText Label="Methods">A systematic review was performed.</AbstractText>
     </Abstract>
     <AuthorList>
       <Author><LastName>Mar</LastName><Initials>K</Initials></Author>
       <Author><LastName>Smith</LastName><Initials>J</Initials></Author>
       <Author><LastName>Lee</LastName><Initials>A</Initials></Author>
     </AuthorList>
     <PublicationTypeList><PublicationType>Systematic Review</PublicationType></PublicationTypeList>
   </Article></MedlineCitation>
   <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1111/ajd.99999</ArticleId></ArticleIdList></PubmedData>
 </PubmedArticle>
 <PubmedArticle><MedlineCitation>
   <PMID>22222222</PMID>
   <Article>
     <Journal><ISOAbbreviation>Australas J Dermatol</ISOAbbreviation>
       <JournalIssue><Volume>66</Volume><Issue>3</Issue><PubDate><Year>2025</Year></PubDate></JournalIssue></Journal>
     <ArticleTitle>A short letter on dermoscopy.</ArticleTitle>
     <Pagination><MedlinePgn>186-187</MedlinePgn></Pagination>
     <AuthorList><Author><LastName>Corio</LastName><Initials>A</Initials></Author></AuthorList>
     <PublicationTypeList><PublicationType>Letter</PublicationType></PublicationTypeList>
   </Article></MedlineCitation>
   <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1111/ajd.88888</ArticleId></ArticleIdList></PubmedData>
 </PubmedArticle>
</PubmedArticleSet>"""

def selftest():
    recs = parse_articles(SAMPLE_XML)
    assert len(recs) == 2, recs
    q = {"journal_short": "AJD", "mode": "issue",
         "sections": {"review": "Reviews", "original": "Originals", "case": "Cases", "letter": "Letters"}}
    rows = []
    for r in recs:
        sec, badge = classify(r, q)
        rows.append((r["pmid"], r["authors"], badge, sec, cite_str(r), bool(r["abstract"])))
    print("Parsed & classified sample XML (offline):")
    for pmid, auth, badge, sec, cite, hasabs in rows:
        print(f"  {pmid} | {auth:<14} | {badge:<18} | {sec:<9} | {cite} | abstract={hasabs}")
    a = recs[0]
    assert a["authors"] == "Mar K, et al.", a["authors"]
    assert "Background:" in a["abstract"] and "Methods:" in a["abstract"]
    assert cite_str(a) == "Australas J Dermatol. 2025;66(3):119-126"
    assert rows[0][2] == "Systematic review" and rows[0][3] == "Reviews"
    assert rows[1][2] == "Letter" and rows[1][3] == "Letters"
    print("\nself-test OK ✓  (parser, author formatting, abstract labels, citation, classification)")

# -------------------------------------------------------------------- main ---
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fetch journal-club articles from PubMed/NCBI.")
    ap.add_argument("--scope", default=os.path.join(HERE, "scope.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "articles.json"))
    ap.add_argument("--selftest", action="store_true", help="offline parser/classifier check")
    ap.add_argument("--dry-run", action="store_true", help="fetch + classify, print, do not write")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        sys.exit(0)

    with open(args.scope, encoding="utf-8") as f:
        scope = json.load(f)
    print(f"Fetching {len(scope['queries'])} queries from PubMed/NCBI…")
    articles = run(scope)
    payload = {"generated": time.strftime("%Y-%m-%d"),
               "source": "PubMed/NCBI (MEDLINE)", "articles": articles}
    print(f"\nTotal: {len(articles)} articles ({sum(1 for a in articles if a['abstract'])} with abstracts)")
    if args.dry_run:
        print("(--dry-run: not writing)")
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"Wrote {args.out}. Now run:  python3 {os.path.relpath(os.path.join(HERE,'generate_report.py'))}")
