#!/usr/bin/env python3
"""
Journal-club article scan generator.

Builds a self-contained HTML reading list for the Prince of Wales Hospital
(POWH) Department of Dermatology journal club.

Scope requested:
  * JAAD (J Am Acad Dermatol) - CME / original / review, April-May 2025
  * AJD  (Australas J Dermatol) - whole May 2025 issue
  * BJD  (Br J Dermatol) - review articles, February-March 2025

Data source: PubMed / NCBI (MEDLINE), retrieved 2026-06-17.

IMPORTANT METHODOLOGY NOTE
--------------------------
PubMed's publication-date filter mixes "online-first" dates with print-issue
dates, so a naive date-range search over-captures articles destined for later
issues and misses issue content posted online earlier. To match what a reader
sees in the printed issues, every journal was scoped by VOLUME + ISSUE, which
maps to the cover month as follows (verified against PubMed citation strings):
    JAAD  Vol 92 Issue 4 = Apr 2025 ; Issue 5 = May 2025
    AJD   Vol 66 Issue 3 = May 2025   (cover date May, despite earlier e-pub)
    BJD   Vol 192 Issue 2 = Feb 2025 ; Issue 3 = Mar 2025

Re-run:  python3 generate_report.py   ->   ../journal-club-derm-2025.html
"""

from datetime import date
from html import escape

GENERATED = "2026-06-17"

# ----------------------------------------------------------------------------
# Data.  authors = display string already abbreviated ("Surname IN, et al.").
# Titles keep PubMed's HTML numeric entities (they render correctly in HTML).
# ----------------------------------------------------------------------------

def art(pmid, doi, authors, title, cite, badge, note=""):
    return dict(pmid=pmid, doi=doi, authors=authors, title=title,
                cite=cite, badge=badge, note=note)

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
    art("39645042", "10.1016/j.jaad.2024.11.050", "Kj&#xe6;rsgaard Andersen R, et al.",
        "A genome-wide association meta-analysis links hidradenitis suppurativa to common and rare sequence variants causing disruption of the Notch and Wnt/&#x3b2;-catenin signaling pathways.",
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
    art("39637982", "10.1016/j.jaad.2024.09.086", "Vall&#xe9;e S, et al.",
        "Long-term evolution of prepubertal-onset anogenital lichen sclerosus: A 35-year retrospective and cross-sectional study from a single tertiary care maternal and pediatric center.",
        "J Am Acad Dermatol. 2025;92(5):1010-1014", "Original"),
    art("39855347", "10.1016/j.jaad.2024.12.041", "Murat de Montai Q, et al.",
        "Interferon-&#x3b1; biological activity is associated with disease activity and risk of flare in cutaneous lupus erythematosus: A monocentric study of 184 patients.",
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
        "Haematogenous seeding in mycosis fungoides and S&#xe9;zary syndrome: current evidence and clinical implications.",
        "Br J Dermatol. 2025;192(3):381-389", "Review"),
]

# Adjacent reviews caught by the Feb-Mar online window but belonging to the
# February HS-themed supplement (S1) and the April issue (192/4).
BJD_SUPPL = [
    art("39895594", "10.1093/bjd/ljae238", "Frew JW",
        "Unravelling the complex pathogenesis of hidradenitis suppurativa.",
        "Br J Dermatol. 2025;192(Suppl 1):i3-i14", "Review (HS suppl, Feb)"),
    art("39895593", "10.1093/bjd/ljae399", "Petukhova L, et al.",
        "Leveraging genotypes and phenotypes to implement precision medicine in hidradenitis suppurativa management.",
        "Br J Dermatol. 2025;192(Suppl 1):i22-i29", "Review (HS suppl, Feb)"),
    art("39895591", "10.1093/bjd/ljae318", "Sayed CJ, et al.",
        "An evolutionary tale on clinical trials in hidradenitis suppurativa.",
        "Br J Dermatol. 2025;192(Suppl 1):i15-i21", "Review (HS suppl, Feb)"),
]

BJD_APRIL = [
    art("39844356", "10.1093/bjd/ljae491", "Barker JN, et al.",
        "Global Delphi consensus on treatment goals for generalized pustular psoriasis.",
        "Br J Dermatol. 2025;192(4):706-716", "Systematic review / Consensus (Apr)"),
    art("39841178", "10.1093/bjd/ljae456", "Chang LY, et al.",
        "Evolution of long scalp hair in humans.",
        "Br J Dermatol. 2025;192(4):574-584", "Review (Apr)"),
    art("39520387", "10.1093/bjd/ljae443", "Hua VK, et al.",
        "Disabling pansclerotic morphoea: a century of discovery.",
        "Br J Dermatol. 2025;192(4):585-596", "Review (Apr)"),
]

# ----------------------------------------------------------------------------

def badge_class(badge):
    b = badge.lower()
    if "cme" in b:               return "b-cme"
    if "guideline" in b or "consensus" in b: return "b-guide"
    if "meta" in b or "systematic" in b:     return "b-meta"
    if "review" in b or "viewpoint" in b:    return "b-review"
    if "case" in b:              return "b-case"
    if "letter" in b:            return "b-letter"
    if "short" in b:             return "b-short"
    return "b-orig"

def render_item(a):
    doi_url = f"https://doi.org/{a['doi']}"
    pm_url = f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/"
    note = f'<div class="note">{escape(a["note"])}</div>' if a["note"] else ""
    return f"""        <li class="art">
          <span class="badge {badge_class(a['badge'])}">{a['badge']}</span>
          <a class="title" href="{doi_url}" target="_blank" rel="noopener">{a['title']}</a>
          <div class="meta">{a['authors']} &middot; <span class="cite">{a['cite']}</span></div>
          {note}
          <div class="links"><a href="{doi_url}" target="_blank" rel="noopener">DOI</a> <span>&middot;</span> <a href="{pm_url}" target="_blank" rel="noopener">PubMed {a['pmid']}</a></div>
        </li>"""

def render_group(name, items, subtitle=""):
    sub = f' <span class="gcount">{subtitle}</span>' if subtitle else ""
    body = "\n".join(render_item(a) for a in items)
    return f"""      <h3 class="grp">{name} <span class="gcount">({len(items)})</span>{sub}</h3>
      <ul class="arts">
{body}
      </ul>"""

total = (len(JAAD_REVIEWS)+len(JAAD_ORIGINAL)+len(AJD_REVIEWS)+len(AJD_ORIGINAL)
         +len(AJD_CASES)+len(AJD_LETTERS)+len(BJD_MARCH)+len(BJD_SUPPL)+len(BJD_APRIL))

CSS = """
:root{--bg:#fafafa;--surface:#fff;--surface2:#f4f4f5;--border:#e4e4e7;--text:#18181b;--text2:#52525b;--text3:#71717a;--accent:#0f766e;--accent-bg:#ccfbf1;}
@media (prefers-color-scheme:dark){:root{--bg:#09090b;--surface:#18181b;--surface2:#27272a;--border:#27272a;--text:#fafafa;--text2:#a1a1aa;--text3:#71717a;--accent:#2dd4bf;--accent-bg:#134e4a;}}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);line-height:1.55;font-size:16px;padding:40px 20px}
.wrap{max-width:980px;margin:0 auto}
h1{font-size:28px;font-weight:700;letter-spacing:-.4px;margin-bottom:4px}
.sub{color:var(--text2);font-size:15px;margin-bottom:2px}
.date{color:var(--text3);font-size:12.5px;font-family:ui-monospace,'JetBrains Mono',monospace;margin-top:10px}
.summary{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin:24px 0}
.summary h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--text3);margin-bottom:12px}
.sgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}
.scard{background:var(--surface2);border-radius:9px;padding:12px 14px}
.scard .n{font-size:24px;font-weight:700;color:var(--accent)}
.scard .l{font-size:12.5px;color:var(--text2);margin-top:2px}
section{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px 24px;margin-bottom:22px}
section>h2{font-size:20px;font-weight:700;margin-bottom:2px}
section>.scope{color:var(--text2);font-size:13.5px;margin-bottom:6px}
.grp{font-size:14px;font-weight:700;color:var(--accent);margin:20px 0 8px;text-transform:uppercase;letter-spacing:.04em}
.gcount{color:var(--text3);font-weight:500;text-transform:none;letter-spacing:0}
ul.arts{list-style:none}
li.art{padding:12px 0;border-top:1px solid var(--border)}
li.art:first-child{border-top:none}
.title{font-weight:600;color:var(--text);text-decoration:none;font-size:15.5px}
.title:hover{color:var(--accent);text-decoration:underline}
.meta{color:var(--text2);font-size:13.5px;margin-top:3px}
.cite{font-family:ui-monospace,'JetBrains Mono',monospace;font-size:12.5px}
.note{font-size:12.5px;color:var(--text3);margin-top:3px;font-style:italic}
.links{font-size:12px;margin-top:5px}
.links a{color:var(--accent);text-decoration:none}
.links a:hover{text-decoration:underline}
.links span{color:var(--text3)}
.badge{display:inline-block;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;padding:2px 7px;border-radius:5px;margin-right:7px;vertical-align:1px}
.b-cme{background:#fef3c7;color:#b45309}.b-review{background:#ede9fe;color:#6d28d9}.b-meta{background:#dbeafe;color:#1d4ed8}
.b-guide{background:#dcfce7;color:#15803d}.b-orig{background:var(--accent-bg);color:var(--accent)}.b-case{background:#f4f4f5;color:#52525b}
.b-letter{background:#fee2e2;color:#b91c1c}.b-short{background:#f4f4f5;color:#71717a}
@media (prefers-color-scheme:dark){.b-cme{background:#422006;color:#fbbf24}.b-review{background:#2e1065;color:#a78bfa}.b-meta{background:#1e3a8a;color:#60a5fa}.b-guide{background:#14532d;color:#4ade80}.b-letter{background:#450a0a;color:#f87171}.b-case,.b-short{background:#27272a;color:#a1a1aa}}
.callout{background:var(--surface2);border-left:3px solid var(--accent);border-radius:6px;padding:11px 14px;font-size:13.5px;color:var(--text2);margin:10px 0 4px}
footer{color:var(--text3);font-size:12.5px;line-height:1.7;margin-top:8px;padding:0 4px}
footer code{font-family:ui-monospace,monospace;background:var(--surface2);padding:1px 5px;border-radius:4px}
"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>POWH Dermatology Journal Club — Article Scan</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Dermatology Journal Club — Article Scan</h1>
    <div class="sub">Prince of Wales Hospital (POWH), Department of Dermatology</div>
    <div class="sub">JAAD (Apr–May 2025) &middot; AJD (May 2025) &middot; BJD reviews (Feb–Mar 2025)</div>
    <div class="date">Compiled {GENERATED} &middot; Source: PubMed / NCBI (MEDLINE) &middot; {total} articles</div>
  </header>

  <div class="summary">
    <h2>At a glance</h2>
    <div class="sgrid">
      <div class="scard"><div class="n">{len(JAAD_REVIEWS)+len(JAAD_ORIGINAL)}</div><div class="l">JAAD — CME/review + original</div></div>
      <div class="scard"><div class="n">{len(AJD_REVIEWS)+len(AJD_ORIGINAL)+len(AJD_CASES)+len(AJD_LETTERS)}</div><div class="l">AJD — full May issue</div></div>
      <div class="scard"><div class="n">{len(BJD_MARCH)}</div><div class="l">BJD — reviews in Feb &amp; Mar issues</div></div>
      <div class="scard"><div class="n">{len(BJD_SUPPL)+len(BJD_APRIL)}</div><div class="l">BJD — adjacent (suppl/Apr)</div></div>
    </div>
  </div>

  <section>
    <h2>1 · Journal of the American Academy of Dermatology (JAAD)</h2>
    <div class="scope">April–May 2025 &middot; Volume 92, Issues 4 (Apr) &amp; 5 (May) &middot; scope: CME / original / review</div>
    <div class="callout">CME designation is inferred from JAAD's multi-part review series (Sunscreens I/II, Psoriatic arthritis I/II); PubMed carries no explicit "CME" tag, so confirm against the issue contents page. The two issues also contained ≈149 research letters, correspondence, case reports, editorials and errata, which fall outside the requested CME/original/review scope and are not listed here.</div>
{render_group("CME &amp; Review articles", JAAD_REVIEWS)}
{render_group("Original articles", JAAD_ORIGINAL)}
  </section>

  <section>
    <h2>2 · Australasian Journal of Dermatology (AJD)</h2>
    <div class="scope">May 2025 &middot; Volume 66, Issue 3 (cover date May 2025) &middot; scope: complete issue</div>
{render_group("Reviews, systematic reviews &amp; viewpoints", AJD_REVIEWS)}
{render_group("Original &amp; research articles", AJD_ORIGINAL)}
{render_group("Case reports &amp; case series", AJD_CASES)}
{render_group("Letters / correspondence", AJD_LETTERS)}
  </section>

  <section>
    <h2>3 · British Journal of Dermatology (BJD)</h2>
    <div class="scope">Review articles &middot; February–March 2025 &middot; Volume 192, Issues 2 (Feb) &amp; 3 (Mar)</div>
    <div class="callout">The <b>February issue (192/2) contained no review-type articles</b> (verified by issue-level search). The March issue (192/3) contained the two reviews below. For completeness, reviews that appeared online during Feb–Mar but belong to the February HS-themed supplement and the April issue are listed separately — include or drop these depending on how you define the window.</div>
{render_group("Reviews — March issue (192/3)", BJD_MARCH)}
{render_group("Adjacent — February HS supplement (192/S1)", BJD_SUPPL, subtitle="optional")}
{render_group("Adjacent — April issue (192/4), online in Feb–Mar", BJD_APRIL, subtitle="optional")}
  </section>

  <footer>
    <p><b>Method.</b> Articles were retrieved from PubMed/NCBI and scoped by <code>journal + volume + issue</code> rather than raw publication-date ranges, because PubMed mixes online-first and print-issue dates (a naive date search over-returns later-issue content and misses issue articles posted online earlier). Issue→month mapping was verified against PubMed citation strings.</p>
    <p><b>Attribution.</b> Bibliographic data &copy; the respective publishers, indexed by the U.S. National Library of Medicine (PubMed). Every entry links to its DOI and PubMed record. Always cite the primary source.</p>
    <p>Regenerate with <code>python3 journal-club/generate_report.py</code>.</p>
  </footer>
</div>
</body>
</html>
"""

if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(__file__), "..", "journal-club-derm-2025.html")
    out = os.path.abspath(out)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {out}  ({total} articles, {len(html)} bytes)")
