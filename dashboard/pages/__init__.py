"""ACD Dashboard — Page registry."""
from dashboard.pages import (
    overview, profiles, publications, impact, funding,
    trials, heatmap, collaboration, benchmarking, experts,
    chatbot, methodology,
)

REGISTRY = [
    overview,
    profiles,
    publications,
    impact,
    funding,
    trials,
    heatmap,
    collaboration,
    benchmarking,
    experts,
    chatbot,
    methodology,
]

PAGE_MAP = {page.PAGE_HREF: page for page in REGISTRY}
