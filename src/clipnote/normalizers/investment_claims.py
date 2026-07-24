"""Normalize only representation details; never invent investment evidence."""
from .common import mmss_to_sec


def normalize_investment_claims(data: dict) -> dict:
    for claim in data.get("claims", []):
        anchor = claim.get("source_anchor")
        if isinstance(anchor, dict):
            anchor["timestamp_start"] = mmss_to_sec(
                anchor.get("timestamp_start"))
            anchor["timestamp_end"] = mmss_to_sec(
                anchor.get("timestamp_end"))
    return data

