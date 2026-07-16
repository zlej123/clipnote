import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import analyze
import capture
import export as exporter
import render as renderer
from contract import validate
from common import analysis_file, frames_dir, output_dir, video_id


class CoreContractTests(unittest.TestCase):
    def valid_data(self):
        return {
            "title": "테스트 가이드",
            "summary": "요약",
            "category": "공예",
            "materials": [{"name": "종이", "amount": "1장"}],
            "steps": [
                {"id": 1, "summary": "접기", "detail": "종이를 접는다.",
                 "t_start": 0, "t_end": 10},
            ],
            "visual_guides": [
                {"id": "vg-1", "step_id": 1, "source_phrase": "fold it",
                 "phrase": "종이를 반으로 접기", "type": "action",
                 "what_to_show": "두 모서리가 만나는 장면",
                 "best_visual_timestamp": 8,
                 "guide_text": "두 모서리가 정확히 겹치도록 반으로 접는다.",
                 "importance": 0.9},
            ],
            "_duration": 20,
            "_profile": "generic",
            "_output_language": "ko",
            "_max_visual_guides": 5,
        }

    def test_valid_independent_visual_guides(self):
        errors, _ = validate(self.valid_data())
        self.assertEqual([], errors)

    def test_legacy_step_ambiguity_is_rejected(self):
        data = self.valid_data()
        data["steps"][0]["ambiguity"] = None
        errors, _ = validate(data)
        self.assertTrue(any("legacy ambiguity" in error for error in errors))

    def test_unknown_step_reference_is_rejected(self):
        data = self.valid_data()
        data["visual_guides"][0]["step_id"] = 999
        errors, _ = validate(data)
        self.assertTrue(any("없는 step_id" in error for error in errors))

    def test_normalize_visual_guide_timestamp(self):
        data = self.valid_data()
        data["steps"][0]["t_start"] = "0:01"
        data["steps"][0]["t_end"] = "1:02"
        data["visual_guides"][0]["best_visual_timestamp"] = "0:08"
        normalized = analyze.normalize(data)
        self.assertEqual(1, normalized["steps"][0]["t_start"])
        self.assertEqual(62, normalized["steps"][0]["t_end"])
        self.assertEqual(8, normalized["visual_guides"][0]["best_visual_timestamp"])

    def test_normalize_repairs_common_model_variants(self):
        data = self.valid_data()
        guide = data["visual_guides"][0]
        guide.pop("source_phrase")
        guide.pop("importance")
        guide["type"] = "direction"
        normalized = analyze.normalize(data)
        repaired = normalized["visual_guides"][0]
        self.assertEqual(guide["phrase"], repaired["source_phrase"])
        self.assertEqual("position", repaired["type"])
        self.assertIn("_normalization_warnings", normalized)

    def test_video_id_parses_all_url_forms(self):
        self.assertEqual("GC_Szxdqh2Y", video_id("https://www.youtube.com/watch?v=GC_Szxdqh2Y"))
        self.assertEqual("Ff9BQUkhTZ4", video_id("https://www.youtube.com/shorts/Ff9BQUkhTZ4"))
        self.assertEqual("4ioPBiTWm3M", video_id("https://youtu.be/4ioPBiTWm3M"))
        with self.assertRaises(ValueError):
            video_id("https://example.com/not-a-video")

    def test_prompt_injects_user_language_and_limits(self):
        prompt = analyze.load_prompt("generic", "6:41", "ja", 7)
        self.assertIn("ja", prompt)
        self.assertIn("7개 이하", prompt)
        self.assertNotIn("{OUTPUT_LANGUAGE}", prompt)
        self.assertNotIn("{MAX_VISUAL_GUIDES}", prompt)

    def test_artifact_paths_are_variant_aware(self):
        self.assertIn("generic.ko.json", str(analysis_file(ROOT, "abc", "generic", "ko")))
        self.assertNotEqual(frames_dir(ROOT, "abc", "generic", "ko"),
                            frames_dir(ROOT, "abc", "generic", "en"))
        self.assertNotEqual(output_dir(ROOT, "abc", "recipe", "ko"),
                            output_dir(ROOT, "abc", "generic", "ko"))


class ExplicitSelectionTests(unittest.TestCase):
    def test_no_pick_never_auto_selects(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / "vg-1_center.jpg").write_bytes(b"image")
            self.assertIsNone(renderer.choose_frame("vg-1", {}, path))

    def test_client_image_refs_override_disk_frames(self):
        data = CoreContractTests().valid_data()
        with tempfile.TemporaryDirectory() as temp:
            images_dir = Path(temp) / "images"
            images_dir.mkdir()
            ctx = renderer.build_context(
                "video", data, {}, Path(temp) / "no-frames", images_dir,
                image_refs={"vg-1": "https://cdn.example.com/vg-1.jpg"})
            guide = ctx["steps"][0]["visual_guides"][0]
            self.assertTrue(guide["has_screenshot"])
            self.assertEqual("https://cdn.example.com/vg-1.jpg", guide["screenshot"])

    def test_explicit_pick_selects_exact_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            candidate = path / "vg-1_before.jpg"
            candidate.write_bytes(b"image")
            self.assertEqual(candidate, renderer.choose_frame(
                "vg-1", {"vg-1": "before"}, path))

    def test_none_pick_forces_link_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(renderer.choose_frame(
                "vg-1", {"vg-1": "none"}, Path(temp)))

    def test_candidates_span_linked_step(self):
        step = {"t_start": 6, "t_end": 15}
        guide = {"best_visual_timestamp": 7}
        self.assertEqual(
            {"before": 5, "center": 7, "after": 16},
            capture.candidate_times(step, guide, 30))


class ExportTests(unittest.TestCase):
    def test_bundle_and_obsidian_export(self):
        data = CoreContractTests().valid_data()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rendered = root / "rendered"
            (rendered / "images").mkdir(parents=True)
            (rendered / "images" / "vg-1_action.jpg").write_bytes(b"image")
            document = rendered / "document.md"
            document.write_text("![장면](images/vg-1_action.jpg)\n", encoding="utf-8")

            bundle = root / "bundle"
            exporter.export_bundle(data, rendered, document, bundle,
                                   "video", "generic", "ko")
            self.assertTrue((bundle / "manifest.json").exists())
            self.assertTrue((bundle / "images" / "vg-1_action.jpg").exists())

            vault = root / "vault"
            target = exporter.export_obsidian(data, rendered, document, vault,
                                              "video", "generic", "ko")
            text = target.read_text(encoding="utf-8")
            self.assertIn("attachments/테스트 가이드/vg-1_action.jpg", text)
            manifest = json.loads((vault / "테스트 가이드.manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("ko", manifest["output_language"])

            (rendered / "images" / "vg-1_action.jpg").unlink()
            pdf = exporter.export_goodnotes(
                data, rendered, root / "goodnotes", "video")
            self.assertTrue(pdf.exists())
            self.assertGreater(pdf.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
