# app/risk/scoring.py

from typing import Dict, Any, List

CANONICAL = [
    "cybersecurity",
    "data_privacy",
    "financial",
    "operational",
    "regulatory",
    "reputation",
    "supplychain"
]

def compute_scores_from_watchlists(watchlist_categories: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Deterministic scoring based on real watchlist severity.
    Scoring rule:
        - base score = 20
        - add severity_sum * 40 (tunable)
    """
    scores = {}

    for cat in watchlist_categories:
        name = cat.get("category")
        entries = cat.get("entries", []) or []

        severities = [
            e.get("severity", 0.0)
            for e in entries
            if isinstance(e, dict)
        ]
        severity_sum = sum(severities)

        # BASE SCORE
        base = 20.0

        # If no entries -> base score was correct
        if severities:
            score = base + (severity_sum * 40.0)
        else:
            score = base

        # Clamp 0–100
        if score > 100:
            score = 100.0

        scores[name] = round(score, 1)

    # Ensure all canonical categories exist
    for c in CANONICAL:
        scores.setdefault(c, 20.0)

    return scores
