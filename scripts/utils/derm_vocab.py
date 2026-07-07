"""Dermatology-relevance vocabulary and vectorised classifier.

Single source of truth for all dermatology keyword lists used by the
relevance-tagging pipeline (06_tag_derm_relevance.py) and the topic
classifier (09_classify_missing_topics.py).

Three tiers of matching, applied in order:
  1. Topic/SubTopic field tokens  — OpenAlex taxonomy labels
  2. MeSH descriptor tokens       — pipe-joined MeSH terms on each work
  3. Title/Abstract tokens        — hard-signal stems in free text
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Tier 1 — OpenAlex Topic_Field / SubTopic / Topic_SubField_Display / Keywords
# ---------------------------------------------------------------------------
DERM_FIELD_TOKENS: tuple[str, ...] = (
    "dermatology",
    "dermatological",
    "skin cancer",
    "melanoma",
    "psoriasis",
    "eczema",
    "atopic dermatitis",
    "acne",
    "rosacea",
    "vitiligo",
    "alopecia",
    "skin biopsy",
    "phototherapy",
    "immunodermatology",
    "cosmetic dermatology",
    "paediatric dermatology",
    "pediatric dermatology",
    "procedural dermatology",
    "mohs surgery",
    "laser therapy",
    "wound healing",
    "cutaneous",
    "skin disease",
    "skin disorder",
    "skin infection",
    "skin inflammation",
    "skin neoplasm",
    "basal cell",
    "squamous cell carcinoma",
    "dermoscopy",
    "dermatoscopy",
    "photodynamic therapy",
    "contact dermatitis",
    "urticaria",
    "pemphigus",
    "pemphigoid",
    "bullous",
    "hidradenitis",
    "ichthyosis",
    "seborrhoeic",
    "seborrheic",
    "tinea",
    "onychomycosis",
    "nail disorder",
    "hair disorder",
    "hyperhidrosis",
    "pruritus",
    "xerosis",
    "scabies",
    "wart",
    "molluscum",
    "herpes zoster",
    "lupus erythematosus",
    "scleroderma",
    "morphoea",
    "morphea",
    "vasculitis",
    "pyoderma",
    "keloid",
    "scar",
    "wound",
    "sun damage",
    "photoprotection",
    "sunscreen",
    "ultraviolet",
    "uv radiation",
)

# ---------------------------------------------------------------------------
# Tier 2 — MeSH descriptor tokens
# ---------------------------------------------------------------------------
DERM_MESH_TOKENS: tuple[str, ...] = (
    "dermatology",
    "skin diseases",
    "skin neoplasms",
    "melanoma",
    "carcinoma, basal cell",
    "carcinoma, squamous cell",
    "psoriasis",
    "dermatitis",
    "dermatitis, atopic",
    "eczema",
    "acne vulgaris",
    "rosacea",
    "vitiligo",
    "alopecia",
    "phototherapy",
    "skin biopsy",
    "mohs surgery",
    "laser therapy",
    "wound healing",
    "cutaneous",
    "urticaria",
    "pemphigus",
    "pemphigoid, bullous",
    "hidradenitis suppurativa",
    "ichthyosis",
    "dermoscopy",
    "photodynamic therapy",
    "contact dermatitis",
    "tinea",
    "onychomycosis",
    "hyperhidrosis",
    "pruritus",
    "scabies",
    "herpes zoster",
    "lupus erythematosus, cutaneous",
    "scleroderma",
    "vasculitis",
    "keloid",
    "sunscreening agents",
    "ultraviolet rays",
    "skin aging",
    "photoaging",
    "sebaceous glands",
    "hair diseases",
    "nail diseases",
    "sweat glands",
    "seborrheic dermatitis",
    "pyoderma",
    "erythema",
    "exanthema",
    "drug eruptions",
)

# ---------------------------------------------------------------------------
# Tier 3 — Title / Abstract hard-signal stems
# ---------------------------------------------------------------------------
DERM_TITLE_ABSTRACT_TOKENS: tuple[str, ...] = (
    "dermatol",
    "melanom",
    "skin cancer",
    "basal cell",
    "squamous cell carcinom",
    "psoriasis",
    "eczema",
    "atopic dermatit",
    "vitiligo",
    "alopecia",
    "rosacea",
    "acne",
    "cutaneous",
    "mohs",
    "phototherap",
    "skin biopsy",
    "dermoscop",
    "dermatoscop",
    "immunodermatol",
    "paediatric derm",
    "pediatric derm",
    "cosmetic derm",
    "photodynamic therap",
    "contact dermatit",
    "urticaria",
    "pemphigus",
    "pemphigoid",
    "bullous",
    "hidradenitis",
    "ichthyosis",
    "onychomycosis",
    "hyperhidrosis",
    "pruritus",
    "scabies",
    "herpes zoster",
    "lupus erythematosus",
    "scleroderma",
    "morphoea",
    "morphea",
    "vasculitis",
    "pyoderma",
    "keloid",
    "sunscreen",
    "photoprotect",
    "ultraviolet",
    "uv radiation",
    "skin aging",
    "photoaging",
    "seborrhoeic",
    "seborrheic",
    "tinea",
    "nail disorder",
    "hair disorder",
    "wound heal",
    "skin wound",
    "drug eruption",
    "erythema multiforme",
    "toxic epidermal",
    "stevens-johnson",
)

# ---------------------------------------------------------------------------
# Vectorised classifier — same interface as rehab_vocab.py
# ---------------------------------------------------------------------------

def _col_matches(df: pd.DataFrame, col: str, tokens: tuple[str, ...]) -> pd.Series:
    """Case-insensitive substring test across a column, vectorised."""
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    s = df[col].astype("string").fillna("").str.strip()
    s_nopipe = s.str.replace("|", "", regex=False).str.strip()
    lo = s.str.lower()
    pattern = "|".join(
        pd.Series(tokens).str.replace(
            r"([\\.^$*+?()\[\]{}|])", r"\\\1", regex=True
        )
    )
    hit = lo.str.contains(pattern, regex=True, na=False)
    return hit & (s_nopipe != "")


def vectorized_relevance(pubs: pd.DataFrame) -> pd.Series:
    """Return a boolean Series indicating dermatology-relevance per row."""
    hits = (
        _col_matches(pubs, "Topic_Field", DERM_FIELD_TOKENS)
        | _col_matches(pubs, "SubTopic", DERM_FIELD_TOKENS)
        | _col_matches(pubs, "Topic_SubField_Display", DERM_FIELD_TOKENS)
        | _col_matches(pubs, "Keywords", DERM_FIELD_TOKENS)
        | _col_matches(pubs, "MESH_Terms", DERM_MESH_TOKENS)
        | _col_matches(pubs, "Title", DERM_TITLE_ABSTRACT_TOKENS)
        | _col_matches(pubs, "Abstract", DERM_TITLE_ABSTRACT_TOKENS)
    )
    return hits
