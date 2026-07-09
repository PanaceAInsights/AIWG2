"""Visual system — colors, typography, plotly template.

ACD Research Intelligence Platform — dark aubergine palette.
  BG_MAIN      #1B1424  deep aubergine background
  BG_CARD      #2A1F33  card background
  BG_SIDEBAR   #221830  sidebar background
  COPPER       #C27D4E  primary accent
  TEXT_SECONDARY #ECE7DF warm cream
  TEXT_MUTED   #A89DB8  muted purple-grey
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# ── Core dark palette ─────────────────────────────────────────────────────────
BG_MAIN        = "#1B1424"   # deep aubergine — page background
BG_CARD        = "#2A1F33"   # card surface
BG_SIDEBAR     = "#221830"   # sidebar background
BG_HOVER       = "#33243F"   # hover state for nav items
COPPER         = "#C27D4E"   # primary accent
COPPER_LIGHT   = "#D9956A"   # lighter copper — hover, badges
COPPER_DARK    = "#A0623A"   # darker copper — pressed
TEXT_PRIMARY   = "#FFFFFF"
TEXT_SECONDARY = "#ECE7DF"   # warm cream
TEXT_MUTED     = "#A89DB8"   # muted purple-grey
BORDER         = "#3D2F4A"   # subtle border
TIER_HIGH      = "#4CAF50"
TIER_REVIEW    = "#FF9800"
TIER_NOT_FOUND = "#9E9E9E"

# ── Chart palette ─────────────────────────────────────────────────────────────
CHART_PALETTE = [
    "#C27D4E",  # copper
    "#7B5EA7",  # medium purple
    "#4CAF50",  # green
    "#E8A87C",  # light copper
    "#9C6FBF",  # lavender
    "#FF9800",  # orange
    "#5C9BD6",  # steel blue
    "#E57373",  # rose
    "#81C784",  # light green
    "#64B5F6",  # light blue
]
PALETTE = CHART_PALETTE  # alias

# ── Legacy aliases ────────────────────────────────────────────────────────────
PRIMARY        = COPPER
PRIMARY_LIGHT  = COPPER_LIGHT
PRIMARY_SOFT   = "#3D2F4A"
ACCENT         = "#7B5EA7"
SUCCESS        = TIER_HIGH
WARNING        = TIER_REVIEW
DANGER         = "#EF4444"
VIOLET         = "#7B5EA7"
CYAN           = "#5C9BD6"
PINK           = "#E57373"

INK            = BG_MAIN
GRAY_900       = BG_CARD
GRAY_700       = "#4A3A5A"
GRAY_500       = TEXT_MUTED
GRAY_300       = BORDER
GRAY_200       = BORDER
GRAY_100       = BG_CARD
GRAY_50        = BG_HOVER
WHITE          = TEXT_PRIMARY

BLUE_VIOLET    = "#7B5EA7"
DEEP_AUBERGINE = BG_MAIN
DARK_PLUM      = BG_SIDEBAR
MAUVE          = TEXT_MUTED
MAUVE_PURPLE   = "#7B5EA7"
WARM_CREAM     = TEXT_SECONDARY
BURNT_COPPER   = COPPER_DARK
LIGHT_COPPER   = COPPER_LIGHT
COPPER_ACCENT  = COPPER
SOFT_PURPLE    = "#9C6FBF"
MUTED_GREY     = TEXT_MUTED
CHART_GREEN    = TIER_HIGH
CHART_ORANGE   = TIER_REVIEW
TIER_LOW       = "#EF4444"

BG_CARD_HOVER  = BG_HOVER
ACCENT_PRIMARY = COPPER
ACCENT_HOVER   = COPPER_LIGHT
ACCENT_LIGHT   = COPPER_LIGHT
NAV_ACTIVE_BG  = COPPER
NAV_HOVER_BG   = BG_HOVER
BORDER_COLOR   = BORDER
FONT_FAMILY    = "Inter, -apple-system, system-ui, sans-serif"
FONT_MONO      = "'JetBrains Mono', 'Fira Code', 'Courier New', monospace"
SIDEBAR_WIDTH  = "240px"
TOPBAR_HEIGHT  = "60px"
CARD_RADIUS    = "10px"
CARD_PADDING   = "20px"
CARD_SHADOW    = "0 4px 20px rgba(0,0,0,0.4)"

CARD_STYLE = {
    "backgroundColor": BG_CARD,
    "border": f"1px solid {BORDER}",
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
    "color": TEXT_PRIMARY,
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

PLOTLY_LAYOUT = {}  # No-op; use register_plotly_template()

def apply_plotly_theme(fig):
    """Apply the ACD theme to any Plotly figure (legacy helper)."""
    return fig


# ── Mantine theme ─────────────────────────────────────────────────────────────
MANTINE_THEME = {
    "colorScheme": "dark",
    "primaryColor": "copper",
    "colors": {
        "copper": [
            "#FDF0E8", "#F7D9C0", "#EFC09A", "#E5A374",
            "#D9956A", "#C27D4E", "#A0623A", "#7D4A2A",
            "#5C341C", "#3D2010",
        ],
        "dark": [
            "#ECE7DF", "#C8BFCF", "#A89DB8", "#8A7AA0",
            "#6B5A88", "#4D3D6E", "#3D2F4A", "#2A1F33",
            "#221830", "#1B1424",
        ],
    },
    "fontFamily": "Inter, -apple-system, system-ui, sans-serif",
    "headings": {"fontFamily": "Inter, -apple-system, sans-serif"},
    "defaultRadius": "md",
    "components": {
        "Card": {
            "defaultProps": {"withBorder": True, "radius": "md"},
        },
        "Paper": {"defaultProps": {"shadow": "xs", "radius": "lg", "withBorder": True}},
        "Button": {"defaultProps": {"radius": "md"}},
        "Tabs": {"defaultProps": {"radius": "md"}},
    },
}


# ── Plotly template ───────────────────────────────────────────────────────────
def register_plotly_template() -> None:
    """Register the 'acd' Plotly template and set it as default."""
    layout = go.Layout(
        paper_bgcolor=BG_CARD,
        plot_bgcolor=BG_CARD,
        font=dict(family=FONT_FAMILY, color=TEXT_SECONDARY, size=12),
        title=dict(font=dict(color=TEXT_PRIMARY, size=15), x=0.01, xanchor="left"),
        colorway=CHART_PALETTE,
        xaxis=dict(
            gridcolor=BORDER,
            linecolor=BORDER,
            tickcolor=TEXT_MUTED,
            tickfont=dict(color=TEXT_MUTED),
            title=dict(font=dict(color=TEXT_MUTED)),
            zerolinecolor=BORDER,
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor=BORDER,
            linecolor=BORDER,
            tickcolor=TEXT_MUTED,
            tickfont=dict(color=TEXT_MUTED),
            title=dict(font=dict(color=TEXT_MUTED)),
            zerolinecolor=BORDER,
            zeroline=False,
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT_SECONDARY),
            bordercolor=BORDER,
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        hoverlabel=dict(
            bgcolor=BG_SIDEBAR,
            bordercolor=COPPER,
            font=dict(color=TEXT_PRIMARY),
        ),
        margin=dict(l=48, r=16, t=48, b=40),
    )
    template = go.layout.Template(layout=layout)
    pio.templates["acd"] = template
    pio.templates.default = "acd"
