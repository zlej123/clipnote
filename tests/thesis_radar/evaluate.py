#!/usr/bin/env python3
"""Evaluate one extraction after a human maps predicted claims to gold claims."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "src"))

from clipnote.claim_evaluation import (  # noqa: E402
    evaluate_claims,
    evaluate_quality_gate,
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prediction")
    parser.add_argument("gold")
    parser.add_argument("review")
    args = parser.parse_args()
    result = evaluate_claims(
        read_json(args.prediction),
        read_json(args.gold),
        read_json(args.review),
    )
    corpus = read_json(Path(__file__).with_name("corpus.json"))
    gate = evaluate_quality_gate(result, corpus["quality_gate"])
    print(json.dumps(
        {"metrics": result, "quality_gate": gate},
        ensure_ascii=False,
        indent=2,
    ))
    if not gate["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
