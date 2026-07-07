"""ACD Research Intelligence Platform — Design tokens and theme constants.

Palette source: Australasian College of Dermatologists brand colours.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
DEEP_AUBERGINE  = "#1B1424"   # Main dark background
DARK_PLUM       = "#3D3149"   # Left panel / secondary dark purple
MAUVE_PURPLE    = "#814C7E"   # Bottom navigation bar / wave
MUTED_VIOLET    = "#553E51"   # Shadow purple / transition tone
COPPER          = "#C27D4E"   # Main ACD gold-orange tone (primary accent)
BURNT_COPPER    = "#AD6A3C"   # Darker orange gradient
LIGHT_COPPER    = "#D99561"   # Highlight / date banner
WARM_CREAM      = "#ECE7DF"   # Softer off-white text
WHITE           = "#FFFFFE"   # Main text
BLUE_VIOLET     = "#575571"   # Subtle right-side glow / muted accent

# Semantic aliases
BG_MAIN         = DEEP_AUBERGINE
BG_SIDEBAR      = DARK_PLUM
BG_CARD         = "#2A1F33"   # Slightly lighter than BG_MAIN for cards
BG_CARD_HOVER   = "#33253D"
ACCENT_PRIMARY  = COPPER
ACCENT_HOVER    = BURNT_COPPER
ACCENT_LIGHT    = LIGHT_COPPER
TEXT_PRIMARY    = WHITE
TEXT_SECONDARY  = WARM_CREAM
TEXT_MUTED      = "#A89DB8"
BORDER_COLOR    = MUTED_VIOLET
NAV_ACTIVE_BG   = MAUVE_PURPLE
NAV_HOVER_BG    = MUTED_VIOLET

# Confidence tier colours
TIER_HIGH       = "#4CAF50"   # green
TIER_REVIEW     = "#FF9800"   # amber
TIER_LOW        = "#F44336"   # red
TIER_NOT_FOUND  = "#9E9E9E"   # grey

# Chart colours (sequential + categorical)
CHART_PALETTE = [
    COPPER, MAUVE_PURPLE, LIGHT_COPPER, BLUE_VIOLET,
    BURNT_COPPER, "#9B6B9B", "#E8B07A", "#7A7098",
    "#F0C896", "#6B5B8A", "#D4956A", "#4A3D5E",
]

# Plotly template overrides
PLOTLY_LAYOUT = dict(
    paper_bgcolor=BG_MAIN,
    plot_bgcolor=BG_CARD,
    font=dict(family="Inter, Helvetica Neue, Arial, sans-serif", color=TEXT_SECONDARY, size=12),
    title_font=dict(color=WHITE, size=15, family="Inter, Helvetica Neue, Arial, sans-serif"),
    legend=dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_SECONDARY, size=11),
    ),
    xaxis=dict(
        gridcolor=BORDER_COLOR,
        linecolor=BORDER_COLOR,
        tickcolor=TEXT_MUTED,
        tickfont=dict(color=TEXT_MUTED),
        zerolinecolor=BORDER_COLOR,
    ),
    yaxis=dict(
        gridcolor=BORDER_COLOR,
        linecolor=BORDER_COLOR,
        tickcolor=TEXT_MUTED,
        tickfont=dict(color=TEXT_MUTED),
        zerolinecolor=BORDER_COLOR,
    ),
    colorway=CHART_PALETTE,
    margin=dict(l=50, r=20, t=50, b=50),
    hoverlabel=dict(
        bgcolor=DARK_PLUM,
        font_color=WHITE,
        bordercolor=COPPER,
    ),
)

# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
FONT_FAMILY = "Inter, 'Helvetica Neue', Arial, sans-serif"
FONT_MONO   = "'JetBrains Mono', 'Fira Code', 'Courier New', monospace"

# ---------------------------------------------------------------------------
# Spacing / sizing
# ---------------------------------------------------------------------------
SIDEBAR_WIDTH   = "240px"
TOPBAR_HEIGHT   = "60px"
CARD_RADIUS     = "10px"
CARD_PADDING    = "20px"
CARD_SHADOW     = f"0 4px 20px rgba(0,0,0,0.4)"

# ---------------------------------------------------------------------------
# Dash Bootstrap / inline style helpers
# ---------------------------------------------------------------------------
CARD_STYLE = {
    "backgroundColor": BG_CARD,
    "border": f"1px solid {BORDER_COLOR}",
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

def apply_plotly_theme(fig):
    """Apply the ACD theme to any Plotly figure."""
    fig.update_layout(**PLOTLY_LAYOUT)
    return fig
