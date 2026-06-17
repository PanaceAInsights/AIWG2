#!/usr/bin/env python3
"""
Journal-club builder for the Prince of Wales Hospital (POWH) Department of
Dermatology journal club.

Emits three self-contained artifacts from one source of truth:
  1. journal-club-derm-2025.html   - printable reading list / dossier (abstracts inline)
  2. journal-club-derm-2025.csv    - one row per paper incl. abstract (Excel/EndNote-friendly)
  3. journal-club-dashboard.html   - interactive dashboard: search, filter, per-paper cards

Scope (scoped by volume+issue, not raw publication date - see README note below):
  * JAAD (J Am Acad Dermatol)  - CME / original / review : Vol 92, Iss 4 (Apr) + 5 (May) 2025
  * AJD  (Australas J Dermatol) - whole May 2025 issue     : Vol 66, Iss 3
  * BJD  (Br J Dermatol)        - review articles          : Vol 192, Iss 2-3 (Feb-Mar) + adjacent

Data source: PubMed / NCBI (MEDLINE), retrieved 2026-06-17.
Abstracts are loaded from journal-club/abstracts.json (keyed by PMID).

Run:  python3 journal-club/generate_report.py
"""

import os, re, csv, json, html

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
GENERATED = "2026-06-17"

with open(os.path.join(HERE, "abstracts.json"), encoding="utf-8") as fh:
    ABSTRACTS = json.load(fh)


def art(pmid, doi, authors, title, cite, badge, note=""):
    return dict(pmid=pmid, doi=doi, authors=authors, title=title,
                cite=cite, badge=badge, note=note)


# ---------------------------------------------------------------- data -------
JAAD_REVIEWS = [
    art("38772426", "10.1016/j.jaad.2024.02.065", "Abdel Azim S, et al.",
        "Sunscreens part 1: Mechanisms and efficacy.",
        "J Am Acad Dermatol. 2025;92(4):677-686", "CME / Review"),
    art("38777185", "10.1016/j.jaad.2024.02.066", "Abdel Azim S, et al.",
        "Sunscreens part 2: Regulation and safety.",
        "J Am Acad Dermatol. 2025;92(4):689-698", "CME / Review"),
    art("39549844", "10.1016/j.jaad.2024.10.081", "Curtis KL, et al.",
        "Diagnosis and management of subungual and periungual verruca: A clinical review.",
        "J Am Acad Dermatol. 2025;92(4):861-871", "Review"),
    art("39725212", "10.1016/j.jaad.2024.11.071", "Alhusayen R, et al.",
        "North American clinical practice guidelines for the medical management of hidradenitis suppurativa in special patient populations.",
        "J Am Acad Dermatol. 2025;92(4):825-852", "Guideline"),
    art("39709077", "10.1016/j.jaad.2024.12.016", "Burshtein J, et al.",
        "The association between obesity and efficacy of psoriasis therapies: An expert consensus panel.",
        "J Am Acad Dermatol. 2025;92(4):807-815", "Consensus"),
    art("39645042", "10.1016/j.jaad.2024.11.050", "Kjærsgaard Andersen R, et al.",
        "A genome-wide association meta-analysis links hidradenitis suppurativa to common and rare sequence variants causing disruption of the Notch and Wnt/β-catenin signaling pathways.",
        "J Am Acad Dermatol. 2025;92(4):761-772", "Meta-analysis"),
    art("38857765", "10.1016/j.jaad.2024.03.058", "Perez-Chada LM, et al.",
        "Psoriatic arthritis: A comprehensive review for the dermatologist part I: Epidemiology, comorbidities, pathogenesis, and diagnosis.",
        "J Am Acad Dermatol. 2025;92(5):969-982", "CME / Review"),
    art("38857766", "10.1016/j.jaad.2024.03.059", "Elman SA, et al.",
        "Psoriatic arthritis: A comprehensive review for the dermatologist-Part II: Screening and management.",
        "J Am Acad Dermatol. 2025;92(5):985-998", "CME / Review"),
    art("39889854", "10.1016/j.jaad.2024.11.082", "Zakhem GA, et al.",
        "Prevalence of poor outcomes in cutaneous squamous cell carcinoma by AJCC and BWH tumor stages: A systematic review and meta-analysis.",
        "J Am Acad Dermatol. 2025;92(5):1064-1071", "Systematic review"),
]

JAAD_ORIGINAL = [
    art("39631697", "10.1016/j.jaad.2024.11.043", "Schonmann Y, et al.",
        "Evaluating cancer risk in a large cohort of 25,008 patients with vitiligo: Insights from a comprehensive cohort population-based study.",
        "J Am Acad Dermatol. 2025;92(4):741-752", "Original"),
    art("39637987", "10.1016/j.jaad.2024.11.047", "Nicholas A, et al.",
        "Race and appointment availability influence continuity of care for chronic inflammatory skin disease: A cross-sectional study of United States practice data.",
        "J Am Acad Dermatol. 2025;92(4):753-760", "Original"),
    art("39657847", "10.1016/j.jaad.2024.11.057", "Hundal S, et al.",
        "Cost-utility analysis of clinic-based deroofing versus local excision for hidradenitis suppurativa.",
        "J Am Acad Dermatol. 2025;92(4):773-780", "Original"),
    art("39709076", "10.1016/j.jaad.2024.11.066", "Gao P, et al.",
        "Early diagnosis of type 2 diabetes mellitus in patients with psoriasis: Construction of a multifactorial diagnostic model.",
        "J Am Acad Dermatol. 2025;92(4):790-800", "Original"),
    art("39706528", "10.1016/j.jaad.2024.11.067", "Boudreaux B, et al.",
        "Oncologic outcomes for invasive squamous cell carcinoma with a clinically resolved biopsy site managed by watchful waiting: A retrospective cohort study.",
        "J Am Acad Dermatol. 2025;92(4):801-806", "Original"),
    art("39637982", "10.1016/j.jaad.2024.09.086", "Vallée S, et al.",
        "Long-term evolution of prepubertal-onset anogenital lichen sclerosus: A 35-year retrospective and cross-sectional study from a single tertiary care maternal and pediatric center.",
        "J Am Acad Dermatol. 2025;92(5):1010-1014", "Original"),
    art("39855347", "10.1016/j.jaad.2024.12.041", "Murat de Montai Q, et al.",
        "Interferon-α biological activity is associated with disease activity and risk of flare in cutaneous lupus erythematosus: A monocentric study of 184 patients.",
        "J Am Acad Dermatol. 2025;92(5):1039-1048", "Original"),
    art("39880172", "10.1016/j.jaad.2025.01.052", "Hagino T, et al.",
        "A 96-week real-world outcome of upadacitinib treatment for atopic dermatitis: Systemic therapy-naive versus -experienced patients.",
        "J Am Acad Dermatol. 2025;92(5):1049-1055", "Original"),
    art("39884581", "10.1016/j.jaad.2024.12.043", "Ficheux AS, et al.",
        "Predictors of perceived stress, perceived stigmatization, and body dysmorphia in patients with chronic prurigo/prurigo nodularis: Results from an observational cross-sectional multicenter European study in 17 countries.",
        "J Am Acad Dermatol. 2025;92(5):1056-1063", "Original"),
    art("39848587", "10.1016/j.jaad.2024.11.078", "Valdes Morales KL, et al.",
        "Nail unit melanoma treated with Mohs micrographic surgery: Technique, local recurrence rate, and surgical outcomes.",
        "J Am Acad Dermatol. 2025;92(5):1072-1079", "Original"),
]

AJD_REVIEWS = [
    art("39992008", "10.1111/ajd.14429", "So N, et al.",
        "Paediatric Hypotrichosis: A Clinical and Algorithmic Approach to Diagnosis.",
        "Australas J Dermatol. 2025;66(3):e109-e119", "Review"),
    art("40095285", "10.1111/ajd.14454", "Welc N, et al.",
        "High-Intensity Focused Ultrasound-Application, Effects and Complications.",
        "Australas J Dermatol. 2025;66(3):e120-e125", "Review"),
    art("40095204", "10.1111/ajd.14451", "Li GX, et al.",
        "Targeted Therapies for Slow-Flow Vascular Malformations.",
        "Australas J Dermatol. 2025;66(3):142-151", "Review"),
    art("39953770", "10.1111/ajd.14432", "Mar K, et al.",
        "Prevention of Post-Inflammatory Hyperpigmentation in Skin of Colour: A Systematic Review.",
        "Australas J Dermatol. 2025;66(3):119-126", "Systematic review"),
    art("39927601", "10.1111/ajd.14424", "Cowan TL, et al.",
        "Systematic Review of Rare Major Adverse Cardiovascular Events Associated With the Treatment of Acne With Isotretinoin.",
        "Australas J Dermatol. 2025;66(3):e97-e108", "Systematic review"),
    art("39912292", "10.1111/ajd.14428", "Kow CS, et al.",
        "Spironolactone for the Treatment of Moderate to Severe Acne in Adult Women: A Systematic Review and Meta-Analysis of Randomised Controlled Trials.",
        "Australas J Dermatol. 2025;66(3):165-168", "Systematic review / Meta-analysis"),
    art("39907196", "10.1111/ajd.14423", "Hang X, Lim DS",
        "Australian Sunscreens: The Price of Protection for Skin of Colour With Pigmentary Disorders.",
        "Australas J Dermatol. 2025;66(3):e80-e96", "Review"),
    art("39895543", "10.1111/ajd.14426", "Warren LJ, Krishnan S",
        "Laryngeal Squamous Cell Carcinoma and Diathermy Plume.",
        "Australas J Dermatol. 2025;66(3):162-164", "Review"),
    art("39907175", "10.1111/ajd.14427", "Li GX, et al.",
        "Biosimilars for Australian Dermatologists.",
        "Australas J Dermatol. 2025;66(3):152-156", "Viewpoint"),
]

AJD_ORIGINAL = [
    art("40071648", "10.1111/ajd.14449", "Mendi BI, et al.",
        "Clinical Characteristics, Management and Long-Term Outcomes of 180 Patients With Early-Stage Mycosis Fungoides at a Tertiary Centre-A 34-Year Retrospective Study.",
        "Australas J Dermatol. 2025;66(3):e126-e139", "Original"),
    art("40066906", "10.1111/ajd.14453", "Johns M, et al.",
        "Comparison of Keratinocyte Cancer Tumour and Defect Sizes Treated by Mohs Micrographic Surgery: Sydney Versus Outside Metropolitan Sydney.",
        "Australas J Dermatol. 2025;66(3):e148-e154", "Original"),
    art("40028779", "10.1111/ajd.14450", "May F, et al.",
        "Drug Survival of Biological Therapies in Smokers and Non-Smokers With Psoriasis: A Retrospective Cohort Study Using Data From the Australasian Psoriasis Registry.",
        "Australas J Dermatol. 2025;66(3):e140-e147", "Original"),
    art("40008491", "10.1111/ajd.14433", "Iyengar L, et al.",
        "#Acne: A Thematic Qualitative Analysis of Acne Content on TikTok.",
        "Australas J Dermatol. 2025;66(3):127-134", "Original"),
    art("40008490", "10.1111/ajd.14442", "Tran A, et al.",
        "Treatment of Benign Adnexal Tumours With Mohs Micrographic Surgery: An Australian Retrospective Analysis.",
        "Australas J Dermatol. 2025;66(3):e163-e166", "Original"),
    art("39953774", "10.1111/ajd.14434", "Guttentag A, et al.",
        "A Guide to Screening for Autoimmune Diseases in Patients With Vulvar Lichen Sclerosus.",
        "Australas J Dermatol. 2025;66(3):135-141", "Original"),
    art("39976264", "10.1111/ajd.14435", "Lim PN, et al.",
        "Ergonomics in Dermatological Surgery: An International Survey Among Dermatologists.",
        "Australas J Dermatol. 2025;66(3):e155-e159", "Original"),
    art("40019052", "10.1111/ajd.14444", "Eassa BI, et al.",
        "Efficacy of Topical Oxytocin With Micro-Needling in the Treatment of Facial Skin Ageing: A Randomised, Placebo-Controlled, Split-Face Study.",
        "Australas J Dermatol. 2025;66(3):172-174", "Original (RCT)"),
    art("40040562", "10.1111/ajd.14448", "Yap M, et al.",
        "Rural Exposure and Future Intent of Australian Dermatology Trainees.",
        "Australas J Dermatol. 2025;66(3):e176-e178", "Short report"),
]

AJD_CASES = [
    art("39891469", "10.1111/ajd.14425", "Tran V, et al.",
        "Acneiform Eruption Secondary to Deucravacitinib: A Case Series and Review of the Literature.",
        "Australas J Dermatol. 2025;66(3):157-161", "Case series / Review"),
    art("39921367", "10.1111/ajd.14431", "Holmes Z, et al.",
        "Upadacitinib for Chronic Actinic Dermatitis: A Case Report and Literature Review of JAK Inhibitor Use for Recalcitrant Disease.",
        "Australas J Dermatol. 2025;66(3):169-171", "Case report"),
    art("40189739", "10.1111/ajd.14456", "LaMonica LC, et al.",
        "Case Report of Dermatomyositis With Features of the Wong Variant Developing Post-Trastuzumab Therapy for Breast Cancer.",
        "Australas J Dermatol. 2025;66(3):183-185", "Case report"),
    art("40110971", "10.1111/ajd.14430", "Sakamoto S, et al.",
        "A Case of Squamous Cell Carcinoma Clinically Thought to be Arising From Bursa of Knee Joint.",
        "Australas J Dermatol. 2025;66(3):175-177", "Case report"),
    art("40110948", "10.1111/ajd.14458", "Stephens R, et al.",
        "Successful Photodynamic Treatment of a Pigmented Nodular BCC Using a Biphasic Activation Protocol.",
        "Australas J Dermatol. 2025;66(3):e179-e181", "Case report"),
    art("40110935", "10.1111/ajd.14459", "Ying Y, et al.",
        "Treating Inverse Lichen Planus With Upadacitinib: A Case Study.",
        "Australas J Dermatol. 2025;66(3):e182-e184", "Case report"),
    art("40084598", "10.1111/ajd.14455", "Wang Y, et al.",
        "Similar Molecular Features in Two Cases of CARD14-Associated Papulosquamous Eruption.",
        "Australas J Dermatol. 2025;66(3):e171-e175", "Case report"),
    art("40019062", "10.1111/ajd.14443", "Wu H, et al.",
        "Novel Compound Heterozygous Mutations in ILNEB Syndrome.",
        "Australas J Dermatol. 2025;66(3):e167-e170", "Case report"),
    art("40019051", "10.1111/ajd.14441", "Halbert AR, et al.",
        "Segmental Congenital Vascular Anomaly With Atrophy, Ulceration and Scarring With Complications in Pregnancy.",
        "Australas J Dermatol. 2025;66(3):e160-e162", "Case report"),
    art("39985234", "10.1111/ajd.14437", "Balan K, et al.",
        "Resolution of Severe Hidradenitis Suppurativa Following Kidney Transplantation.",
        "Australas J Dermatol. 2025;66(3):178-179", "Case report"),
    art("39985229", "10.1111/ajd.14438", "Tran V, et al.",
        "Pellagra and Scurvy in a Patient With Relapsed Schizophrenia.",
        "Australas J Dermatol. 2025;66(3):180-182", "Case report"),
]

AJD_LETTERS = [
    art("40138186", "10.1111/ajd.14439", "Corio A, et al.",
        "Faster Diagnosis, Faster Therapy: Dermoscopy as a Valuable Tool in Difficult Cases of Herpes Zoster.",
        "Australas J Dermatol. 2025;66(3):186-187", "Letter"),
    art("40138172", "10.1111/ajd.14457", "O'Malley S, Hambly R",
        "The Place of the Full Skin Examination in the Digital Landscape.",
        "Australas J Dermatol. 2025;66(3):e185-e186", "Letter"),
]

BJD_MARCH = [
    art("39565404", "10.1093/bjd/ljae457", "Mahmoudi N, et al.",
        "Tailored bioengineering and nanomedicine strategies for sex-specific healing of chronic wounds.",
        "Br J Dermatol. 2025;192(3):390-401", "Review"),
    art("39545505", "10.1093/bjd/ljae441", "Gniadecki R, et al.",
        "Haematogenous seeding in mycosis fungoides and Sézary syndrome: current evidence and clinical implications.",
        "Br J Dermatol. 2025;192(3):381-389", "Review"),
]

BJD_SUPPL = [
    art("39895594", "10.1093/bjd/ljae238", "Frew JW",
        "Unravelling the complex pathogenesis of hidradenitis suppurativa.",
        "Br J Dermatol. 2025;192(Suppl 1):i3-i14", "Review"),
    art("39895593", "10.1093/bjd/ljae399", "Petukhova L, et al.",
        "Leveraging genotypes and phenotypes to implement precision medicine in hidradenitis suppurativa management.",
        "Br J Dermatol. 2025;192(Suppl 1):i22-i29", "Review"),
    art("39895591", "10.1093/bjd/ljae318", "Sayed CJ, et al.",
        "An evolutionary tale on clinical trials in hidradenitis suppurativa.",
        "Br J Dermatol. 2025;192(Suppl 1):i15-i21", "Review"),
]

BJD_APRIL = [
    art("39844356", "10.1093/bjd/ljae491", "Barker JN, et al.",
        "Global Delphi consensus on treatment goals for generalized pustular psoriasis.",
        "Br J Dermatol. 2025;192(4):706-716", "Systematic review / Consensus"),
    art("39841178", "10.1093/bjd/ljae456", "Chang LY, et al.",
        "Evolution of long scalp hair in humans.",
        "Br J Dermatol. 2025;192(4):574-584", "Review"),
    art("39520387", "10.1093/bjd/ljae443", "Hua VK, et al.",
        "Disabling pansclerotic morphoea: a century of discovery.",
        "Br J Dermatol. 2025;192(4):585-596", "Review"),
]

# journal short, journal full, scope label, [(section label, sublabel, items)]
JOURNALS = [
    ("JAAD", "Journal of the American Academy of Dermatology",
     "April–May 2025 · Vol 92, Issues 4 (Apr) & 5 (May) · scope: CME / original / review", [
        ("CME & Review articles", "", JAAD_REVIEWS),
        ("Original articles", "", JAAD_ORIGINAL),
     ]),
    ("AJD", "Australasian Journal of Dermatology",
     "May 2025 · Vol 66, Issue 3 (cover date May 2025) · scope: complete issue", [
        ("Reviews, systematic reviews & viewpoints", "", AJD_REVIEWS),
        ("Original & research articles", "", AJD_ORIGINAL),
        ("Case reports & case series", "", AJD_CASES),
        ("Letters / correspondence", "", AJD_LETTERS),
     ]),
    ("BJD", "British Journal of Dermatology",
     "Review articles · February–March 2025 · Vol 192, Issues 2 (Feb) & 3 (Mar), incl. adjacent", [
        ("Reviews — March issue (192/3)", "", BJD_MARCH),
        ("Reviews — February HS supplement (192/S1)", "", BJD_SUPPL),
        ("Reviews — April issue (192/4), online in Feb–Mar", "", BJD_APRIL),
     ]),
]

# -------------------------------------------------------------- helpers ------
def U(s):
    """Decode any HTML numeric entities to real Unicode."""
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
    for jshort, jfull, scope, sections in JOURNALS:
        for sec_label, _sub, items in sections:
            for a in items:
                jname, year, vol, issue, pages = parse_cite(a["cite"])
                recs.append({
                    "journal": jshort, "journalFull": jfull, "section": sec_label,
                    "type": coarse_type(a["badge"]), "badge": a["badge"],
                    "authors": U(a["authors"]), "title": U(a["title"]),
                    "cite": a["cite"], "year": year, "volume": vol,
                    "issue": issue, "pages": pages,
                    "doi": a["doi"], "doiUrl": f"https://doi.org/{a['doi']}",
                    "pmid": a["pmid"], "pubmedUrl": f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/",
                    "abstract": U(ABSTRACTS.get(a["pmid"], "")),
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

    jaad_n = sum(1 for r in RECORDS if r["journal"] == "JAAD")
    ajd_n = sum(1 for r in RECORDS if r["journal"] == "AJD")
    bjd_n = sum(1 for r in RECORDS if r["journal"] == "BJD")

    sections_html = []
    callouts = {
        "JAAD": '<div class="callout">CME designation is inferred from JAAD\'s multi-part review series (Sunscreens I/II, Psoriatic arthritis I/II); PubMed carries no explicit "CME" tag, so confirm against the issue contents page. ≈149 research letters, correspondence, case reports, editorials and errata in these two issues fall outside the requested CME/original/review scope and are not listed.</div>',
        "BJD": '<div class="callout">The <b>February issue (192/2) contained no review-type articles</b> (verified at issue level). The March issue (192/3) had the two reviews below; reviews from the February HS-themed supplement (192/S1) and the April issue (192/4) that appeared online during Feb–Mar are included here at your request.</div>',
    }
    for i, (jshort, jfull, scope, sections) in enumerate(JOURNALS, 1):
        groups = []
        for sec_label, _sub, _items in sections:
            recs = by_section.get((jshort, sec_label), [])
            lis = "\n".join(report_item(r) for r in recs)
            groups.append(
                f'      <h3 class="grp">{esc(sec_label)} <span class="gcount">({len(recs)})</span></h3>\n'
                f'      <ul class="arts">\n{lis}\n      </ul>')
        sections_html.append(
            f'  <section>\n    <h2>{i} · {esc(jfull)} ({jshort})</h2>\n'
            f'    <div class="scope">{esc(scope)}</div>\n'
            f'    {callouts.get(jshort, "")}\n' + "\n".join(groups) + "\n  </section>")

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
    <div class="date">Compiled {GENERATED} · Source: PubMed / NCBI (MEDLINE) · {len(RECORDS)} articles, {sum(1 for r in RECORDS if r['abstract'])} with abstracts</div>
    <div class="tools">↪ <a href="journal-club-dashboard.html">Interactive dashboard</a> · <a href="journal-club-derm-2025.csv">Download CSV</a></div>
  </header>
  <div class="summary"><h2>At a glance</h2><div class="sgrid">
    <div class="scard"><div class="n">{jaad_n}</div><div class="l">JAAD — CME/review + original</div></div>
    <div class="scard"><div class="n">{ajd_n}</div><div class="l">AJD — full May issue</div></div>
    <div class="scard"><div class="n">{bjd_n}</div><div class="l">BJD — reviews (Feb–Mar, incl. adjacent)</div></div>
    <div class="scard"><div class="n">{len(RECORDS)}</div><div class="l">Total papers</div></div>
  </div></div>
""" + "\n".join(sections_html) + """
  <footer>
    <p><b>Method.</b> Retrieved from PubMed/NCBI and scoped by <code>journal + volume + issue</code> (not raw publication-date ranges), because PubMed mixes online-first and print-issue dates. Issue→month mapping verified against PubMed citation strings.</p>
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
    <div class="date">Compiled {GENERATED} · Source: PubMed / NCBI · {len(RECORDS)} papers · {n_abs} with abstracts · <a href="journal-club-derm-2025.html">reading list</a> · <a href="journal-club-derm-2025.csv">CSV</a></div>
  </header>
  <div class="stats" id="stats"></div>
  <div class="controls">
    <input id="q" type="search" placeholder="Search title, author or abstract…" autocomplete="off">
    <div class="chips" id="jchips"></div>
    <div class="chips" id="tchips"></div>
  </div>
  <div id="count"></div>
  <div id="grid"></div>
  <footer><p>Scoped by journal + volume + issue from PubMed/NCBI. Bibliographic data © the respective publishers (indexed by PubMed); cite the primary source. Regenerate with <code>python3 journal-club/generate_report.py</code>.</p></footer>
</div>
<script>{js}</script>
</body></html>"""

# ----------------------------------------------------------------- main ------
if __name__ == "__main__":
    with open(os.path.join(ROOT, "journal-club-derm-2025.html"), "w", encoding="utf-8") as f:
        f.write(build_report())
    build_csv(os.path.join(ROOT, "journal-club-derm-2025.csv"))
    with open(os.path.join(ROOT, "journal-club-dashboard.html"), "w", encoding="utf-8") as f:
        f.write(build_dashboard())
    n_abs = sum(1 for r in RECORDS if r["abstract"])
    print(f"{len(RECORDS)} papers · {n_abs} abstracts")
    print("wrote: journal-club-derm-2025.html, journal-club-derm-2025.csv, journal-club-dashboard.html")
