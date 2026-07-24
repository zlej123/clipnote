#!/usr/bin/env python3
"""Dispatch normalized analysis validation to the selected profile contract."""
from .contracts.common import validate_common
from .contracts.investment_claims import validate_investment_claims
from .contracts.visual_guides import validate_visual_guides
from .profiles import load_profile

VALIDATORS = {
    "visual_guides": validate_visual_guides,
    "investment_claims": validate_investment_claims,
}


def validate(data: dict):
    errors, warnings = validate_common(data)
    profile = data.get("_profile") or "generic"
    try:
        contract_name = load_profile(profile)["contract"]
    except (ValueError, OSError) as error:
        errors.append(str(error))
        return errors, warnings
    validator = VALIDATORS.get(contract_name)
    if validator is None:
        errors.append(f"알 수 없는 contract: {contract_name}")
        return errors, warnings
    domain_errors, domain_warnings = validator(data)
    return errors + domain_errors, warnings + domain_warnings
