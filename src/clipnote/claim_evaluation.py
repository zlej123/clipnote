"""Deterministic metrics for human-mapped Thesis Radar claim extractions."""
from difflib import SequenceMatcher


def _by_id(items):
    return {item["id"]: item for item in items}


def _normalized(text):
    return " ".join((text or "").lower().split())


def evaluate_claims(prediction: dict, gold: dict, review: dict) -> dict:
    predicted = _by_id(prediction.get("claims", []))
    expected = _by_id(gold.get("claims", []))
    matches = review.get("matches", [])
    matched_prediction_ids = set()
    matched_gold_ids = set()
    type_hits = attribution_hits = quote_hits = 0
    timestamp_errors = []
    critical_errors = []

    for match in matches:
        gold_id = match["gold_id"]
        claim_id = match["claim_id"]
        if gold_id not in expected or claim_id not in predicted:
            raise ValueError(f"unknown reviewed match: {gold_id} -> {claim_id}")
        if gold_id in matched_gold_ids or claim_id in matched_prediction_ids:
            raise ValueError(f"duplicate reviewed match: {gold_id} -> {claim_id}")
        matched_gold_ids.add(gold_id)
        matched_prediction_ids.add(claim_id)
        gold_claim = expected[gold_id]
        predicted_claim = predicted[claim_id]
        type_hits += predicted_claim.get("claim_type") == gold_claim.get("claim_type")
        attribution_correct = bool(match.get("attribution_correct"))
        attribution_hits += attribution_correct
        if gold_claim.get("claim_type") == "recommendation" and not attribution_correct:
            critical_errors.append(
                f"recommendation attribution mismatch: {gold_id} -> {claim_id}")
        gold_quote = _normalized(gold_claim.get("source_anchor", {}).get("quote"))
        predicted_quote = _normalized(
            predicted_claim.get("source_anchor", {}).get("quote"))
        similarity = SequenceMatcher(None, gold_quote, predicted_quote).ratio()
        quote_hits += similarity >= 0.9
        expected_start = gold_claim.get("source_anchor", {}).get("timestamp_start")
        predicted_start = predicted_claim.get(
            "source_anchor", {}).get("timestamp_start")
        if isinstance(expected_start, int) and isinstance(predicted_start, int):
            timestamp_errors.append(abs(expected_start - predicted_start))

    matched = len(matches)
    prediction_count = len(predicted)
    gold_count = len(expected)
    return {
        "prediction_count": prediction_count,
        "gold_count": gold_count,
        "matched_count": matched,
        "precision": matched / prediction_count if prediction_count else 0.0,
        "recall": matched / gold_count if gold_count else 0.0,
        "type_accuracy": type_hits / matched if matched else 0.0,
        "attribution_accuracy": attribution_hits / matched if matched else 0.0,
        "quote_fidelity": quote_hits / matched if matched else 0.0,
        "mean_timestamp_error_seconds": (
            sum(timestamp_errors) / len(timestamp_errors)
            if timestamp_errors else None
        ),
        "false_positive_ids": sorted(set(predicted) - matched_prediction_ids),
        "false_negative_ids": sorted(set(expected) - matched_gold_ids),
        "critical_errors": critical_errors,
    }


DEFAULT_THRESHOLDS = {
    "precision": 0.85,
    "recall": 0.80,
    "type_accuracy": 0.90,
    "attribution_accuracy": 0.95,
    "quote_fidelity": 0.90,
    "max_mean_timestamp_error_seconds": 5.0,
}


def evaluate_quality_gate(metrics: dict, thresholds: dict = None) -> dict:
    thresholds = thresholds or DEFAULT_THRESHOLDS
    failures = []
    for name in (
            "precision", "recall", "type_accuracy",
            "attribution_accuracy", "quote_fidelity"):
        minimum = thresholds[name]
        if metrics[name] < minimum:
            failures.append(f"{name}={metrics[name]:.3f} < {minimum:.3f}")
    timestamp_error = metrics["mean_timestamp_error_seconds"]
    maximum = thresholds["max_mean_timestamp_error_seconds"]
    if timestamp_error is None or timestamp_error > maximum:
        failures.append(
            f"mean_timestamp_error_seconds={timestamp_error} > {maximum:.3f}")
    if metrics["critical_errors"]:
        failures.append(
            f"critical_errors={len(metrics['critical_errors'])}")
    return {"passed": not failures, "failures": failures}
