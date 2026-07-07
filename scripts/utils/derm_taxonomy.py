"""Dermatology topic taxonomy for classifying publications with missing OpenAlex topics.

Each rule is a tuple: (SubTopic_label, Topic_Field_label, [keyword_stems]).
Rules are ordered from most specific to most general. Matching is
case-insensitive substring against Title + Keywords fields.
"""
from __future__ import annotations

TOPIC_RULES: list[tuple[str, str, list[str]]] = [
    # ── Oncology / skin cancer ──────────────────────────────────────────────
    ("Melanoma", "Medicine",
     ["melanom", "melanocyt", "melanocytic"]),
    ("Skin Neoplasms", "Medicine",
     ["skin cancer", "basal cell carcinom", "squamous cell carcinom",
      "merkel cell", "cutaneous lymphom", "mycosis fungoides",
      "sezary", "kaposi", "dermatofibrosarcoma", "angiosarcoma"]),
    ("Mohs Surgery", "Medicine",
     ["mohs", "mohs micrographic", "micrographic surgery"]),
    ("Photodynamic Therapy", "Medicine",
     ["photodynamic therap", "pdt", "aminolevulinic", "methyl aminolevulinat"]),

    # ── Inflammatory / immune-mediated ──────────────────────────────────────
    ("Psoriasis", "Medicine",
     ["psoriasis", "psoriatic"]),
    ("Atopic Dermatitis", "Medicine",
     ["atopic dermatit", "atopic eczema", "eczema"]),
    ("Contact Dermatitis", "Medicine",
     ["contact dermatit", "allergic contact", "irritant contact"]),
    ("Urticaria and Angioedema", "Medicine",
     ["urticaria", "angioedema", "chronic spontaneous urticaria"]),
    ("Autoimmune Blistering Disorders", "Medicine",
     ["pemphigus", "pemphigoid", "bullous", "dermatitis herpetiformis",
      "linear iga", "epidermolysis bullosa"]),
    ("Hidradenitis Suppurativa", "Medicine",
     ["hidradenitis", "acne inversa"]),
    ("Lupus Erythematosus", "Medicine",
     ["lupus erythematosus", "discoid lupus", "subacute cutaneous lupus"]),
    ("Connective Tissue Disorders", "Medicine",
     ["scleroderma", "morphoea", "morphea", "dermatomyositis",
      "mixed connective tissue", "lichen sclerosus"]),
    ("Vasculitis", "Medicine",
     ["vasculitis", "leukocytoclastic", "polyarteritis", "granulomatosis"]),
    ("Rosacea", "Medicine",
     ["rosacea"]),

    # ── Acne and follicular disorders ───────────────────────────────────────
    ("Acne Vulgaris", "Medicine",
     ["acne vulgaris", "acne", "comedone", "isotretinoin"]),

    # ── Pigmentary disorders ─────────────────────────────────────────────────
    ("Vitiligo", "Medicine",
     ["vitiligo"]),
    ("Pigmentary Disorders", "Medicine",
     ["melasma", "hyperpigmentation", "hypopigmentation", "post-inflammatory pigment"]),

    # ── Hair and nail disorders ──────────────────────────────────────────────
    ("Alopecia", "Medicine",
     ["alopecia", "hair loss", "androgenetic", "alopecia areata",
      "telogen effluvium", "scarring alopecia"]),
    ("Nail Disorders", "Medicine",
     ["onychomycosis", "nail disorder", "nail dystrophy", "onycholysis",
      "paronychia", "nail psoriasis"]),

    # ── Infections ──────────────────────────────────────────────────────────
    ("Skin Infections", "Medicine",
     ["tinea", "dermatophyt", "candida", "onychomycosis", "scabies",
      "molluscum", "wart", "verruca", "herpes zoster", "impetigo",
      "cellulitis", "erysipelas", "staphylococcal"]),

    # ── Photomedicine / photoprotection ─────────────────────────────────────
    ("Phototherapy", "Medicine",
     ["phototherap", "narrowband uvb", "psoralen", "puva", "nbuvb",
      "excimer laser"]),
    ("Photoprotection", "Medicine",
     ["sunscreen", "photoprotect", "sun protection", "spf",
      "ultraviolet", "uv radiation", "photoaging", "skin aging"]),

    # ── Procedural / cosmetic ───────────────────────────────────────────────
    ("Procedural Dermatology", "Medicine",
     ["dermoscop", "dermatoscop", "skin biopsy", "cryotherap",
      "curettage", "electrosurgery", "excision", "laser"]),
    ("Cosmetic Dermatology", "Medicine",
     ["cosmetic", "botulinum toxin", "botox", "filler", "hyaluronic acid",
      "chemical peel", "microneedling", "rejuvenation"]),

    # ── Paediatric dermatology ───────────────────────────────────────────────
    ("Paediatric Dermatology", "Medicine",
     ["paediatric derm", "pediatric derm", "neonatal skin",
      "infantile haemangioma", "infantile hemangioma",
      "vascular birthmark", "port-wine stain"]),

    # ── Wound healing ───────────────────────────────────────────────────────
    ("Wound Healing", "Medicine",
     ["wound heal", "chronic wound", "leg ulcer", "pressure ulcer",
      "keloid", "scar", "fibrosis"]),

    # ── Drug reactions ──────────────────────────────────────────────────────
    ("Drug Reactions", "Medicine",
     ["drug eruption", "drug reaction", "stevens-johnson", "toxic epidermal",
      "dress syndrome", "fixed drug"]),

    # ── Genetic / rare skin disorders ───────────────────────────────────────
    ("Genetic Skin Disorders", "Medicine",
     ["ichthyosis", "epidermolysis bullosa", "neurofibromatosis",
      "tuberous sclerosis", "xeroderma pigmentosum", "darier"]),

    # ── General dermatology ─────────────────────────────────────────────────
    ("Dermatology", "Medicine",
     ["dermatol", "cutaneous", "skin disease", "skin disorder"]),

    # ── Epidemiology / public health ─────────────────────────────────────────
    ("Epidemiology", "Medicine",
     ["epidemiol", "prevalence", "incidence", "population-based",
      "cohort study", "case-control", "cross-sectional"]),

    # ── Clinical trials / methodology ───────────────────────────────────────
    ("Clinical Trials", "Medicine",
     ["randomised controlled", "randomized controlled", "rct",
      "clinical trial", "placebo-controlled", "double-blind"]),

    # ── Immunology ──────────────────────────────────────────────────────────
    ("Immunology", "Immunology and Microbiology",
     ["immunolog", "cytokine", "interleukin", "biologic", "dupilumab",
      "secukinumab", "ixekizumab", "ustekinumab", "adalimumab",
      "checkpoint inhibitor", "pd-1", "pd-l1", "ctla-4"]),

    # ── Pathology ───────────────────────────────────────────────────────────
    ("Pathology", "Medicine",
     ["histopathol", "patholog", "dermopathol", "immunohistochem"]),

    # ── General medicine fallback ────────────────────────────────────────────
    ("General Medicine", "Medicine",
     ["medicine", "clinical", "treatment", "therapy", "patient"]),
]
