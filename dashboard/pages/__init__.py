"""ACD Dashboard — Page registry.

Each module exports a ``render()`` callable returning the page layout.
The REGISTRY maps URL paths to page modules.
"""
from . import (
    overview, profiles, publications, impact, collaboration,
    funding, benchmarking, trials, heatmap, experts, methodology, explorer,
    chatbot,  # noqa: F401 — imported for floating widget, not as a page
)

REGISTRY = {
    "/":              overview,
    "/profiles":      profiles,
    "/publications":  publications,
    "/impact":        impact,
    "/collaboration": collaboration,
    "/funding":       funding,
    "/benchmarking":  benchmarking,
    "/trials":        trials,
    "/heatmap":       heatmap,
    "/experts":       experts,
    "/methodology":   methodology,
    "/explorer":      explorer,
}
