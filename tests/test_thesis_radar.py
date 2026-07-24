import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from clipnote import analyze
from clipnote.claim_packet import build_claim_packet
from clipnote.claim_evaluation import evaluate_claims, evaluate_quality_gate
from clipnote.contract import validate
from clipnote.profiles import load_profile
from clipnote.render import build_context, load_template, render


def valid_claim_data():
    return {
        "title": "삼성 파운드리 전망",
        "summary": "영상에서 제시된 투자 주장을 구조화한다.",
        "claims": [{
            "id": "claim-1",
            "statement": "삼성 2나노 수율이 개선됐다는 주장",
            "claim_type": "factual_claim",
            "speaker": "channel_host",
            "epistemic_mode": "asserted",
            "entities": ["005930.KS"],
            "source_anchor": {
                "quote": "2나노 수율이 최근 개선됐습니다",
                "timestamp_start": 522,
                "timestamp_end": 531,
            },
            "time_horizon": None,
            "decision_impact": 3,
            "verification_feasibility": 2,
            "verification_questions": ["공식 양산 자료가 있는가?"],
            "falsification_questions": ["고객사 양산 지연이 확인되는가?"],
        }],
        "_duration": 900,
        "_profile": "investment_claims",
        "_output_language": "ko",
        "_max_claims": 20,
        "_model": "test-model",
    }


class InvestmentContractTests(unittest.TestCase):
    def test_valid_claim_packet_contract(self):
        errors, warnings = validate(valid_claim_data())
        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_model_owned_verification_state_is_rejected(self):
        data = valid_claim_data()
        data["claims"][0]["verification_status"] = "supported"
        errors, _ = validate(data)
        self.assertTrue(any("모델 출력 금지 필드" in error for error in errors))

    def test_source_anchor_is_required(self):
        data = valid_claim_data()
        data["claims"][0]["source_anchor"]["quote"] = ""
        errors, _ = validate(data)
        self.assertTrue(any("source_anchor.quote" in error for error in errors))

    def test_questions_cannot_be_empty(self):
        data = valid_claim_data()
        data["claims"][0]["verification_questions"] = []
        errors, _ = validate(data)
        self.assertTrue(any("verification_questions" in error for error in errors))

    def test_unnamed_entities_may_be_empty_without_forcing_a_guess(self):
        data = valid_claim_data()
        data["claims"][0]["entities"] = []
        errors, _ = validate(data)
        self.assertEqual([], errors)

    def test_invalid_scalar_type_returns_error_instead_of_crashing(self):
        data = valid_claim_data()
        data["claims"][0]["speaker"] = 123
        errors, _ = validate(data)
        self.assertTrue(any("speaker" in error for error in errors))

    def test_claim_normalizer_only_converts_timestamps(self):
        data = valid_claim_data()
        anchor = data["claims"][0]["source_anchor"]
        anchor["timestamp_start"] = "8:42"
        anchor["timestamp_end"] = "8:51"
        normalized = analyze.normalize(data, "investment_claims")
        self.assertEqual(522, anchor["timestamp_start"])
        self.assertEqual(531, anchor["timestamp_end"])
        self.assertNotIn("verification_status", normalized["claims"][0])

    def test_profile_disables_visual_pipeline(self):
        profile = load_profile("investment_claims")
        self.assertFalse(profile["uses_visual_guides"])
        self.assertEqual("investment_claims", profile["contract"])


class ClaimRenderingTests(unittest.TestCase):
    def test_claim_document_and_project_packet_preserve_source_anchor(self):
        data = valid_claim_data()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = build_context(
                "vid00000000", data, {}, root / "frames", root / "images")
            template = load_template("investment_claims").split("\n---\n", 1)[1]
            document = render(template, context)
        self.assertIn("2나노 수율이 최근 개선됐습니다", document)
        self.assertIn("t=522", document)
        packet = build_claim_packet("vid00000000", data)
        self.assertEqual(1, packet["contract_version"])
        self.assertNotIn("verification_status", packet["claims"][0])
        self.assertEqual("unverified", packet["review_queue"][0]["verification_status"])
        self.assertEqual(6, packet["review_queue"][0]["priority_score"])
        self.assertEqual("high", packet["review_queue"][0]["priority_band"])
        self.assertEqual(522, packet["claims"][0]["source_anchor"]["timestamp_start"])

    def test_schema_excludes_system_owned_fields(self):
        schema = json.loads((
            ROOT / "src" / "clipnote" / "skill-core" / "profiles"
            / "investment_claims" / "schema.json"
        ).read_text(encoding="utf-8"))
        claim_properties = schema["properties"]["claims"]["items"]["properties"]
        for field in ("verification_status", "review_status", "source_grade"):
            self.assertNotIn(field, claim_properties)
        packet_schema = json.loads((
            ROOT / "src" / "clipnote" / "skill-core" / "profiles"
            / "investment_claims" / "claim-packet.schema.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(1, packet_schema["properties"]["contract_version"]["const"])

    def test_render_cli_writes_document_and_claim_packet(self):
        video_id = "vid00000000"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analysis = (
                root / "work" / "analyses" / video_id
                / "investment_claims.ko.json"
            )
            analysis.parent.mkdir(parents=True)
            analysis.write_text(
                json.dumps(valid_claim_data(), ensure_ascii=False),
                encoding="utf-8",
            )
            environment = {**os.environ, "CLIPNOTE_DATA": temp}
            result = subprocess.run(
                [
                    sys.executable, "-m", "clipnote.render", video_id,
                    "--profile", "investment_claims", "--language", "ko",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            output = (
                root / "output" / video_id / "investment_claims.ko"
            )
            self.assertTrue((output / "document.md").exists())
            packet = json.loads(
                (output / "claim-packet.json").read_text(encoding="utf-8"))
            self.assertEqual("unverified", packet["review_queue"][0][
                "verification_status"])


class ClaimEvaluationTests(unittest.TestCase):
    def test_metrics_count_misses_hallucinations_and_attribution(self):
        prediction = valid_claim_data()
        prediction["claims"].append({
            **prediction["claims"][0],
            "id": "claim-2",
            "statement": "원문에 없는 주장",
        })
        gold = {
            "claims": [{
                **valid_claim_data()["claims"][0],
                "id": "gold-1",
            }]
        }
        review = {
            "matches": [{
                "gold_id": "gold-1",
                "claim_id": "claim-1",
                "attribution_correct": True,
            }]
        }
        result = evaluate_claims(prediction, gold, review)
        self.assertEqual(0.5, result["precision"])
        self.assertEqual(1.0, result["recall"])
        self.assertEqual(["claim-2"], result["false_positive_ids"])
        self.assertEqual([], result["critical_errors"])
        gate = evaluate_quality_gate(result)
        self.assertFalse(gate["passed"])
        self.assertTrue(any("precision" in failure for failure in gate["failures"]))


class VideoMetadataTests(unittest.TestCase):
    def test_normalize_video_metadata_keeps_attribution_fields(self):
        metadata = analyze.normalize_video_metadata({
            "id": "vid00000000",
            "title": "투자 영상",
            "uploader": "빠른 소식 채널",
            "upload_date": "20260723",
            "duration": 1830.9,
        }, "https://youtu.be/vid00000000")
        self.assertEqual(1830, metadata["duration_seconds"])
        self.assertEqual("빠른 소식 채널", metadata["author"])
        self.assertEqual("2026-07-23", metadata["published_at"])


if __name__ == "__main__":
    unittest.main()
