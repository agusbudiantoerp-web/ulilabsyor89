"""TSFA investor suitability profiling (educational analytics, not investment advice)."""
from __future__ import annotations

from typing import Any


SCORE_MAP = {
    "risk_tolerance": {"Low": 1.0, "Moderate": 2.0, "High": 3.0},
    "risk_capacity": {"Low": 1.0, "Medium": 2.0, "High": 3.0},
    "objective": {
        "Capital Preservation": 1.0,
        "Income": 1.5,
        "Balanced": 2.0,
        "Growth": 2.7,
        "Aggressive Growth": 3.0,
    },
    "horizon": {"Short (under 3 years)": 1.0, "Medium (3–7 years)": 2.0, "Long (over 7 years)": 3.0},
    "liquidity_need": {"High (funds may be needed within 1 year)": 1.0, "Medium (1–3 years)": 2.0, "Low (not expected within 3 years)": 3.0},
    "experience": {"Beginner": 1.0, "Intermediate": 2.0, "Advanced": 3.0},
}

WEIGHTS = {
    "risk_tolerance": 0.25,
    "risk_capacity": 0.25,
    "objective": 0.15,
    "horizon": 0.15,
    "liquidity_need": 0.10,
    "experience": 0.10,
}


def evaluate_investor_profile(answers: dict[str, str]) -> dict[str, Any]:
    """Score six dimensions and apply conservative capacity/liquidity guardrails."""
    missing = [key for key in SCORE_MAP if answers.get(key) not in SCORE_MAP[key]]
    if missing:
        raise ValueError("Jawaban belum valid untuk: " + ", ".join(missing))

    dimension_scores = {key: SCORE_MAP[key][answers[key]] for key in SCORE_MAP}
    raw_score = sum(dimension_scores[k] * WEIGHTS[k] for k in WEIGHTS)
    adjusted_score = raw_score
    guardrails: list[str] = []

    if answers["risk_capacity"] == "Low":
        adjusted_score = min(adjusted_score, 1.55)
        guardrails.append("Risk capacity rendah membatasi profil maksimum ke Conservative/Income.")
    if answers["liquidity_need"].startswith("High"):
        adjusted_score = min(adjusted_score, 1.55)
        guardrails.append("Kebutuhan likuiditas jangka sangat dekat membatasi profil maksimum ke Conservative/Income.")
    if answers["horizon"].startswith("Short"):
        adjusted_score = min(adjusted_score, 1.75)
        guardrails.append("Horizon di bawah 3 tahun membatasi profil maksimum ke Conservative/Income.")

    if adjusted_score < 1.45:
        profile = "Conservative"
    elif adjusted_score < 1.85:
        profile = "Income"
    elif adjusted_score < 2.35:
        profile = "Balanced"
    elif adjusted_score < 2.75:
        profile = "Growth"
    else:
        profile = "Aggressive"

    warnings: list[str] = []
    if answers["risk_tolerance"] == "High" and answers["risk_capacity"] == "Low":
        warnings.append("Risk tolerance tinggi tidak sama dengan kemampuan finansial menanggung kerugian.")
    if answers["objective"] in {"Growth", "Aggressive Growth"} and answers["horizon"].startswith("Short"):
        warnings.append("Tujuan pertumbuhan tinggi tidak selaras dengan horizon investasi yang pendek.")
    if answers["experience"] == "Beginner" and answers["risk_tolerance"] == "High":
        warnings.append("Pengalaman pemula dengan toleransi risiko tinggi memerlukan edukasi dan batas risiko yang jelas.")
    if answers["liquidity_need"].startswith("High") and answers["objective"] in {"Growth", "Aggressive Growth"}:
        warnings.append("Kebutuhan dana dekat waktu bertentangan dengan tujuan pertumbuhan agresif.")

    return {
        "profile": profile,
        "raw_score": round(raw_score, 3),
        "adjusted_score": round(adjusted_score, 3),
        "dimension_scores": dimension_scores,
        "weights": WEIGHTS.copy(),
        "guardrails": guardrails,
        "warnings": warnings,
        "answers": answers.copy(),
        "methodology": "Weighted questionnaire with risk-capacity, liquidity, and horizon guardrails.",
        "disclaimer": "Profil ini merupakan alat penyaringan edukatif, bukan penilaian kesesuaian OJK atau rekomendasi investasi personal.",
    }
