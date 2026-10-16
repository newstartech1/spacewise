"""Deterministic assessment scores for Spacewise room analyses.

The scores deliberately use only the submitted goals and returned analysis data.
They are suitability indicators, not measurements of a room's dimensions.
"""

from typing import Any


def build_assessment(
    selected_goal: str, rekognition_analysis: dict[str, Any], recommendations: list[str]
) -> dict[str, Any]:
    """Return five bounded, repeatable percentage scores and their rule summary."""
    inventory = rekognition_analysis.get("detected_inventory") or []
    quality = (rekognition_analysis.get("image_properties") or {}).get("quality") or {}
    goals = [goal.strip() for goal in selected_goal.split(",") if goal.strip()]
    goal_count = max(1, len(goals))

    confidences = [_number(item.get("confidence")) for item in inventory]
    confidences = [value for value in confidences if value is not None]
    average_confidence = sum(confidences) / len(confidences) if confidences else None
    detected_instances = sum(max(1, int(_number(item.get("instances")) or 0)) for item in inventory)

    sharpness = _number(quality.get("sharpness"))
    contrast = _number(quality.get("contrast"))
    quality_values = [value for value in (sharpness, contrast) if value is not None]
    image_quality = sum(quality_values) / len(quality_values) if quality_values else None

    # Missing data always follows these published baseline values rather than a random estimate.
    design = 35 if average_confidence is None else 30 + (average_confidence * 0.62)
    if image_quality is not None:
        design += (image_quality - 50) * 0.12
    design += min(goal_count, 5) * 2

    utilization = 50 if not inventory else 88 - min(42, (detected_instances * 4) + (len(inventory) * 1.5))
    budget = 60 if not inventory else 84 - min(30, _expensive_item_count(inventory) * 8 + max(0, goal_count - 1) * 3)
    feasibility = 55 if average_confidence is None else 92 - min(35, detected_instances * 2.5) - max(0, 70 - average_confidence) * 0.25
    if recommendations:
        feasibility += min(5, len(recommendations))

    scores = {
        "design_confidence": _score(design),
        "space_utilization": _score(utilization),
        "budget_compatibility": _score(budget),
        "feasibility_confidence": _score(feasibility),
    }
    scores["overall_compatibility"] = _score(
        scores["design_confidence"] * 0.30
        + scores["space_utilization"] * 0.25
        + scores["budget_compatibility"] * 0.20
        + scores["feasibility_confidence"] * 0.25
    )

    return {
        "scores": scores,
        "method": "deterministic-v1",
        "fallback_rules": [
            "No detected inventory: Design Confidence 35%, Space Utilization 50%, and Budget Compatibility 60% baselines are used.",
            "No usable Rekognition confidence: Feasibility Confidence uses a 55% baseline.",
            "Missing image quality is omitted from Design Confidence instead of being estimated.",
            "Overall Compatibility is 30% design, 25% utilization, 20% budget, and 25% feasibility; every result is rounded and clamped from 0% to 100%.",
        ],
    }


def _expensive_item_count(inventory: list[dict[str, Any]]) -> int:
    expensive_terms = {"bed", "couch", "appliance", "television", "monitor", "desk", "dining table"}
    return sum(1 for item in inventory if str(item.get("name", "")).lower() in expensive_terms)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _score(value: float) -> int:
    return max(0, min(100, round(value)))
