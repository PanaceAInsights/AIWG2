"""Visual system — colors, typography, plotly template.

Single source of truth for the ACD Research Intelligence Platform's look-and-feel.
Imported by every page so a palette change here propagates everywhere.
Branding: ACD corporate palette (copper, mauve-purple, warm cream).
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# ---- Brand / ACD palette ------------------------------------------------- #
PRIMARY        = "#B87333"   # ACD copper — primary CTAs, headings, KPIs
PRIMARY_LIGHT  = "#D4956A"   # lighter copper — accents, hover, badges
PRIMARY_SOFT   = "#FDF3E7"   # very light copper background wash
ACCENT         = "#6B4C8A"   # mauve-purple — secondary accent (charts, links)
SUCCESS        = "#10B981"   # emerald — open-access %, positive deltas
WARNING        = "#F59E0B"   # amber — low-confidence, REVIEW badges
DANGER         = "#EF4444"   # red — retractions, negative deltas
VIOLET         = "#6C3483"   # for collaboration chart
CYAN           = "#148F77"   # teal — funding chart
PINK           = "#C0392B"   # warm red — trials chart

# Gray scale
INK      = "#1A1A2E"
GRAY_900 = "#2D2D3A"
GRAY_700 = "#4A4A5A"
GRAY_500 = "#7A7A8A"
GRAY_300 = "#D4D4D4"
GRAY_200 = "#E8E8E8"
GRAY_100 = "#F4F4F4"
GRAY_50  = "#FAFAFA"
WHITE    = "#FFFFFF"

# Legacy aliases used by old pages (copper/mauve theme)
COPPER         = PRIMARY
LIGHT_COPPER   = PRIMARY_LIGHT
MAUVE_PURPLE   = ACCENT
DARK_PLUM      = ACCENT
WARM_CREAM     = GRAY_50
BG_CARD        = WHITE
BORDER_COLOR   = GRAY_200
TEXT_MUTED     = GRAY_500

# Confidence tier colours
TIER_HIGH      = "#10B981"
TIER_REVIEW    = "#F59E0B"
TIER_LOW       = "#EF4444"
TIER_NOT_FOUND = "#9E9E9E"

# Categorical chart palette — ACD-aligned, colour-blind aware.
PALETTE = [
    "#B87333", "#6B4C8A", "#148F77", "#1B4F72", "#D4956A",
    "#F59E0B", "#2980B9", "#E74C3C", "#27AE60", "#8E44AD",
    "#16A085", "#D35400",
]

# ---- Plotly template ----------------------------------------------------- #
def register_plotly_template() -> None:
    """Register 'acd' template and set as default."""
    tpl = go.layout.Template()
    tpl.layout = dict(
        font=dict(family="Inter, -apple-system, system-ui, sans-serif", color=INK, size=13),
        colorway=PALETTE,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=48, r=16, t=48, b=40),
        hoverlabel=dict(
            bgcolor=INK, bordercolor=INK,
            font=dict(color=WHITE, size=12, family="Inter"),
        ),
        xaxis=dict(
            gridcolor=GRAY_200, linecolor=GRAY_300, zeroline=False,
            tickfont=dict(color=GRAY_700, size=11),
            title=dict(font=dict(color=GRAY_700, size=12)),
        ),
        yaxis=dict(
            gridcolor=GRAY_200, linecolor=GRAY_300, zeroline=False,
            tickfont=dict(color=GRAY_700, size=11),
            title=dict(font=dict(color=GRAY_700, size=12)),
        ),
        legend=dict(
            bgcolor="rgba(255,255,255,0.0)",
            font=dict(size=12, color=GRAY_900),
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
        ),
        title=dict(
            font=dict(size=15, color=INK, family="Inter"),
            x=0.0, xanchor="left", y=0.96,
        ),
    )
    pio.templates["acd"] = tpl
    pio.templates.default = "acd"


# ---- Mantine theme overrides --------------------------------------------- #
MANTINE_THEME = {
    "primaryColor": "acd-copper",
    "defaultRadius": "md",
    "fontFamily": "Inter, -apple-system, system-ui, sans-serif",
    "headings": {"fontFamily": "Inter, -apple-system, sans-serif"},
    "colors": {
        # ACD copper scale for Mantine's primary shade
        "acd-copper": [
            "#FDF3E7", "#FAE0C5", "#F5C89A", "#EFAD70", "#D4956A",
            "#C4844E", PRIMARY, "#9A5F28", "#7A4A1E", "#5C3514",
        ],
    },
    "components": {
        "Card": {
            "defaultProps": {
                "shadow": "xs", "radius": "lg",
                "withBorder": True, "padding": "lg",
            }
        },
        "Paper": {"defaultProps": {"shadow": "xs", "radius": "lg", "withBorder": True}},
        "Button": {"defaultProps": {"radius": "md"}},
        "Tabs": {"defaultProps": {"radius": "md"}},
    },
}

# ---- Legacy helpers (kept for backward compatibility) -------------------- #
CHART_PALETTE = PALETTE
PLOTLY_LAYOUT = {}  # No-op; use register_plotly_template() instead

def apply_plotly_theme(fig):
    """Apply the ACD theme to any Plotly figure (legacy helper)."""
    return fig

# ---- Additional legacy aliases for old pages ----------------------------- #
BLUE_VIOLET     = ACCENT
DEEP_AUBERGINE  = INK
BURNT_COPPER    = "#9A5F28"
BG_MAIN         = GRAY_100
BG_SIDEBAR      = PRIMARY
BG_CARD_HOVER   = GRAY_50
ACCENT_PRIMARY  = PRIMARY
ACCENT_HOVER    = PRIMARY_LIGHT
ACCENT_LIGHT    = PRIMARY_LIGHT
TEXT_PRIMARY    = INK
TEXT_SECONDARY  = GRAY_700
NAV_ACTIVE_BG   = PRIMARY_LIGHT
NAV_HOVER_BG    = PRIMARY_SOFT
FONT_FAMILY     = "Inter, -apple-system, system-ui, sans-serif"
FONT_MONO       = "'JetBrains Mono', 'Fira Code', 'Courier New', monospace"
SIDEBAR_WIDTH   = "240px"
TOPBAR_HEIGHT   = "60px"
CARD_RADIUS     = "10px"
CARD_PADDING    = "20px"
CARD_SHADOW     = "0 4px 20px rgba(0,0,0,0.06)"

CARD_STYLE = {
    "backgroundColor": WHITE,
    "border": f"1px solid {GRAY_200}",
    "borderRadius": CARD_RADIUS,
    "padding": CARD_PADDING,
    "boxShadow": CARD_SHADOW,
    "marginBottom": "16px",
}

KPI_STYLE = {
    **CARD_STYLE,
    "textAlign": "center",
    "minHeight": "110px",
    "display": "flex",
    "flexDirection": "column",
    "justifyContent": "center",
}

BADGE_STYLE_HIGH = {
    "backgroundColor": TIER_HIGH,
    "color": WHITE,
    "borderRadius": "4px",
    "padding": "2px 8px",
    "fontSize": "11px",
    "fontWeight": "600",
}

BADGE_STYLE_REVIEW = {
    **BADGE_STYLE_HIGH,
    "backgroundColor": TIER_REVIEW,
}

BADGE_STYLE_NOT_FOUND = {
    **BADGE_STYLE_HIGH,
    "backgroundColor": TIER_NOT_FOUND,
}
