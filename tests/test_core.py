import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from stepkeeper import analyze, capture
from stepkeeper import export as exporter
from stepkeeper import render as renderer
from stepkeeper.contract import validate
from stepkeeper.common import analysis_file, frames_dir, hms, output_dir, video_id


class FixtureCorpusTests(unittest.TestCase):
    def test_en_output_smoke_suite_is_wired(self):
        fixtures = json.loads(
            (ROOT / "tests" / "fixtures" / "urls.json").read_text(encoding="utf-8"))
        suite = fixtures["en_output"]
        self.assertEqual("smoke", suite.get("suite"))
        self.assertEqual("en", suite.get("language"))
        videos = suite["videos"]
        # 영어 출력이 주요 배포 대상이 되면서 4편 → 10편으로 늘렸다 (도메인 6개 커버).
        # 상한은 배치 1회 실행의 무료 티어 사용량을 감당할 수 있는 선.
        self.assertTrue(6 <= len(videos) <= 12, len(videos))
        profiles = {video.get("profile", suite["profile"]) for video in videos}
        self.assertIn("recipe", profiles)
        self.assertIn("generic", profiles)
        for video in videos:
            self.assertEqual("en", video.get("language", suite["language"]))
            self.assertEqual("en", video["strata"]["source_language"])

    def test_fixture_variants_may_share_video_id_across_languages(self):
        """Same YouTube id may appear for ko domain coverage and en_output smoke."""
        fixtures = json.loads(
            (ROOT / "tests" / "fixtures" / "urls.json").read_text(encoding="utf-8"))
        keys = []
        for domain, config in fixtures.items():
            if domain.startswith("_") or not isinstance(config, dict):
                continue
            default_profile = config.get("profile", "generic")
            default_language = config.get("language", "ko")
            for video in config.get("videos", []):
                match = re.search(
                    r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", video["url"])
                self.assertIsNotNone(match, video["url"])
                keys.append((
                    match.group(1),
                    video.get("profile", default_profile),
                    video.get("language", default_language),
                ))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(any(language == "en" for _, _, language in keys))


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

    def test_normalize_keeps_zero_importance(self):
        data = self.valid_data()
        data["visual_guides"][0]["importance"] = 0.0
        normalized = analyze.normalize(data)
        self.assertEqual(0.0, normalized["visual_guides"][0]["importance"])
        self.assertNotIn("_normalization_warnings", normalized)

    def test_asset_digest_tracks_prompt_changes(self):
        d1 = analyze.asset_digest("generic")
        self.assertEqual(12, len(d1))
        self.assertEqual(d1, analyze.asset_digest("generic"))       # 결정적
        self.assertNotEqual(d1, analyze.asset_digest("recipe"))     # 프로파일별로 다름

    def test_normalize_stamps_contract_version(self):
        from stepkeeper.contract import CONTRACT_VERSION
        normalized = analyze.normalize(self.valid_data())
        self.assertEqual(CONTRACT_VERSION, normalized["_contract_version"])
        # 이미 스탬프된 데이터(캐시 재정규화)는 덮어쓰지 않는다
        data = self.valid_data()
        data["_contract_version"] = "0-test"
        self.assertEqual("0-test", analyze.normalize(data)["_contract_version"])

    def test_high_risk_domain_warns(self):
        """의료·전기·가스 등 안전 결정 영상은 경고 채널로 표시된다 (외부 리뷰 #10)."""
        data = self.valid_data()
        data["title"] = "콘센트 전기 배선 교체하기"
        errors, warnings = validate(data)
        self.assertEqual([], errors)
        self.assertTrue(any("고위험" in warning for warning in warnings))

        safe = self.valid_data()
        errors, warnings = validate(safe)
        self.assertFalse(any("고위험" in warning for warning in warnings))

    def test_vague_english_guide_text_warns(self):
        data = self.valid_data()
        data["visual_guides"][0]["guide_text"] = "Cook until done, just enough."
        errors, warnings = validate(data)
        self.assertEqual([], errors)
        self.assertTrue(any("막연 표현" in warning for warning in warnings))

    def test_video_id_parses_all_url_forms(self):
        self.assertEqual("GC_Szxdqh2Y", video_id("https://www.youtube.com/watch?v=GC_Szxdqh2Y"))
        self.assertEqual("Ff9BQUkhTZ4", video_id("https://www.youtube.com/shorts/Ff9BQUkhTZ4"))
        self.assertEqual("4ioPBiTWm3M", video_id("https://youtu.be/4ioPBiTWm3M"))
        with self.assertRaises(ValueError):
            video_id("https://example.com/not-a-video")

    def test_hms_formats_minutes_and_hours(self):
        self.assertEqual("0:08", hms(8))
        self.assertEqual("1:02", hms(62))
        self.assertEqual("1:01:05", hms(3665))

    def test_prompt_injects_user_language_and_limits(self):
        prompt = analyze.load_prompt("generic", "6:41", "ja", 7)
        self.assertIn("ja", prompt)
        self.assertIn("7개 이하", prompt)
        self.assertNotIn("{OUTPUT_LANGUAGE}", prompt)
        self.assertNotIn("{MAX_VISUAL_GUIDES}", prompt)

    def test_template_follows_output_language(self):
        """문서 뼈대(라벨·출처 줄)도 --language를 따라야 한다.

        회귀 방지: 예전에는 template.md가 한국어 하드코딩이라 --language en 문서의
        본문만 영어이고 '준비 재료'·'조리 순서'·'기준:'·'출처:'는 한국어로 남았다.
        """
        for profile in ("recipe", "generic"):
            english = renderer.load_template(profile, "en")
            korean = renderer.load_template(profile, "ko")
            self.assertIn("**■ Steps**", english)
            self.assertIn("kept with stepkeeper", english)
            self.assertNotIn("기준:", english)
            self.assertIn("기준:", korean)
            self.assertIn("stepkeeper로 생성", korean)
            # 번역본이 없는 언어는 영어 기본 뼈대로 떨어진다 (한국어로 새지 않는다)
            japanese = renderer.load_template(profile, "ja")
            self.assertIn("**■ 手順**" if profile == "generic" else "**■ 作り方**", japanese)
            self.assertNotIn("기준:", japanese)
            # 번역본이 없는 언어만 영어로 떨어진다
            self.assertEqual(english, renderer.load_template(profile, "de"))
            self.assertEqual(english, renderer.load_template(profile))

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

    def test_candidates_stay_near_center(self):
        """후보는 스텝 경계가 아니라 center 주변에서 뽑는다.

        회귀 방지(실측): 19초짜리 스텝에서 예전 규칙은 18·31·39초를 뽑았고, 18초는 이전
        섹션·39초는 다음 섹션이라 가이드가 요구한 26~29초 동작이 세 장 어디에도 없었다.
        """
        # 9초 스텝 → spread = 9//4 = 2
        self.assertEqual(
            {"before": 5, "center": 7, "after": 9},
            capture.candidate_times({"t_start": 6, "t_end": 15},
                                    {"best_visual_timestamp": 7}, 30))
        # 19초 스텝이어도 상한 4초를 넘지 않는다 (예전엔 18/39로 벌어졌다)
        self.assertEqual(
            {"before": 27, "center": 31, "after": 35},
            capture.candidate_times({"t_start": 19, "t_end": 38},
                                    {"best_visual_timestamp": 31}, 82))
        # 아주 짧은 스텝에서도 최소 1초는 벌린다 (세 장이 같은 프레임이 되면 선택이 무의미)
        self.assertEqual(
            {"before": 9, "center": 10, "after": 11},
            capture.candidate_times({"t_start": 9, "t_end": 12},
                                    {"best_visual_timestamp": 10}, 30))
        # 스텝 정보가 없으면 종전대로 ±4, 영상 경계로 클램프
        self.assertEqual(
            {"before": 0, "center": 2, "after": 6},
            capture.candidate_times(None, {"best_visual_timestamp": 2}, 30))
        self.assertEqual(
            {"before": 25, "center": 29, "after": 29},
            capture.candidate_times(None, {"best_visual_timestamp": 29}, 30))


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


class AutoPickTests(unittest.TestCase):
    def _seed(self, root: Path):
        os.environ["STEPKEEPER_DATA"] = str(root)
        data = CoreContractTests().valid_data()
        from stepkeeper.common import analysis_file, frames_dir
        source = analysis_file(root, "vid00000000", "generic", "ko")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        frames = frames_dir(root, "vid00000000", "generic", "ko")
        frames.mkdir(parents=True, exist_ok=True)
        for slot in ("before", "center", "after"):
            (frames / f"vg-1_{slot}.jpg").write_bytes(b"\xff\xd8fake")
        return frames

    def tearDown(self):
        os.environ.pop("STEPKEEPER_DATA", None)

    def test_auto_pick_writes_picks_and_meta(self):
        from stepkeeper import autopick
        with tempfile.TemporaryDirectory() as temp:
            frames = self._seed(Path(temp))
            with patch.object(autopick, "generate_json", return_value={
                    "picks": [{"guide_id": "vg-1", "slot": "after",
                               "reason": "목표 상태가 가장 명확"}]}):
                picks = autopick.auto_pick("vid00000000", "generic", "ko", "m", "k")
            self.assertEqual({"vg-1": "after"}, picks)
            saved = json.loads((frames / "picks.json").read_text(encoding="utf-8"))
            self.assertEqual("after", saved["vg-1"])
            meta = json.loads((frames / "picks-meta.json").read_text(encoding="utf-8"))
            self.assertEqual("auto", meta["source"])

    def test_missing_guides_fall_back_to_none(self):
        from stepkeeper import autopick
        with tempfile.TemporaryDirectory() as temp:
            self._seed(Path(temp))
            with patch.object(autopick, "generate_json",
                              return_value={"picks": []}):
                picks = autopick.auto_pick("vid00000000", "generic", "ko", "m", "k")
            self.assertEqual({"vg-1": "none"}, picks)


class FeedbackTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("STEPKEEPER_DATA", None)

    def test_add_and_summary(self):
        from stepkeeper import feedback
        with tempfile.TemporaryDirectory() as temp:
            os.environ["STEPKEEPER_DATA"] = temp
            evaluation = Path(temp) / "semantic-evaluation.json"
            evaluation.write_text(json.dumps({
                "video_id": "v", "profile": "generic", "language": "ko",
                "guides": [
                    {"guide_id": "vg-1", "ai_slot": "center",
                     "selected_slot": "center", "reviewed": True},
                    {"guide_id": "vg-2", "ai_slot": "center",
                     "selected_slot": "after", "reviewed": True},
                    {"guide_id": "vg-3", "ai_slot": None, "reviewed": True},
                ]}), encoding="utf-8")
            self.assertEqual(2, feedback.add(evaluation))
            stats = feedback.summary()
            self.assertEqual(2, stats["total"])
            self.assertEqual(1, stats["agreed"])
            self.assertEqual({"center→after": 1}, stats["disagreements"])


class NotionTests(unittest.TestCase):
    def test_block_building_with_image_and_link(self):
        data = CoreContractTests().valid_data()
        data["visual_guides"].append({
            "id": "vg-2", "step_id": 1, "source_phrase": "x", "phrase": "링크 가이드",
            "type": "state", "what_to_show": "y", "best_visual_timestamp": 9,
            "guide_text": "링크로 확인한다.", "importance": 0.5})
        blocks = exporter.build_notion_blocks(data, "vid00000000", {"vg-1": "upload-1"})
        kinds = [block["type"] for block in blocks]
        self.assertIn("image", kinds)
        image = next(block for block in blocks if block["type"] == "image")
        self.assertEqual("upload-1", image["image"]["file_upload"]["id"])
        links = [block for block in blocks if block["type"] == "paragraph"
                 and block["paragraph"]["rich_text"][0]["text"].get("link")]
        self.assertTrue(any("t=9" in block["paragraph"]["rich_text"][0]["text"]["link"]["url"]
                            for block in links))

    def test_notion_blocks_follow_output_language(self):
        """Notion 절 제목도 --language를 따라야 한다 (문서 뼈대와 같은 규칙).

        회귀 방지: 예전에는 '준비물'·'순서'·'기준:'·'YouTube 원본'이 하드코딩이라
        영어 문서를 Notion으로 보내면 한국어 제목이 붙었다.
        """
        def headings(language, profile="generic"):
            data = CoreContractTests().valid_data()
            data["_output_language"] = language
            data["_profile"] = profile
            blocks = exporter.build_notion_blocks(data, "vid00000000", {})
            return [b["heading_2"]["rich_text"][0]["text"]["content"]
                    for b in blocks if b["type"] == "heading_2"]

        self.assertIn("Steps", headings("en"))
        self.assertIn("What you need", headings("en"))
        self.assertIn("Ingredients", headings("en", profile="recipe"))
        self.assertIn("순서", headings("ko"))
        self.assertIn("준비물", headings("ko"))
        self.assertIn("준비 재료", headings("ko", profile="recipe"))
        self.assertIn("手順", headings("ja"))
        self.assertIn("Steps", headings("de"))          # 번역본 없는 언어는 영어

        data = CoreContractTests().valid_data()
        data["_output_language"] = "en"
        blocks = exporter.build_notion_blocks(data, "vid00000000", {})
        text = json.dumps(blocks, ensure_ascii=False)
        self.assertIn("Watch on YouTube", text)
        self.assertIn("What '", text)                   # 가이드 접두사
        self.assertNotIn("기준:", text)

    def test_export_notion_uploads_and_creates_page(self):
        data = CoreContractTests().valid_data()
        calls = []

        def fake_request(path, token, payload=None, data=None, content_type=None):
            calls.append(path)
            if path == "/file_uploads":
                return {"id": "up-1"}
            if path.startswith("/file_uploads/"):
                return {"status": "uploaded"}
            if path == "/pages":
                self.assertEqual("parent-page", payload["parent"]["page_id"])
                return {"id": "page-1", "url": "https://notion.so/page-1"}
            if path.startswith("/blocks/"):
                return {"results": []}
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as temp:
            rendered = Path(temp)
            (rendered / "images").mkdir()
            (rendered / "images" / "vg-1_action.jpg").write_bytes(b"img")
            with patch.object(exporter, "notion_request", side_effect=fake_request):
                url = exporter.export_notion(data, rendered, "vid00000000",
                                             "parent-page", "tok")
        self.assertEqual("https://notion.so/page-1", url)
        self.assertIn("/file_uploads", calls)
        self.assertIn("/pages", calls)
        # 페이지가 업로드보다 **먼저** — 가장 흔한 실패(부모 페이지 문제)가 업로드 0건으로 끝난다.
        # Notion API에는 업로드 삭제가 없어 순서가 유일한 방어다.
        self.assertLess(calls.index("/pages"), calls.index("/file_uploads"))

    def test_export_notion_uploads_nothing_when_page_creation_fails(self):
        """부모 페이지 오류로 페이지를 못 만들면 이미지는 한 장도 올라가지 않아야 한다."""
        data = CoreContractTests().valid_data()
        calls = []

        def fake_request(path, token, payload=None, data=None, content_type=None):
            calls.append(path)
            if path == "/pages":
                raise RuntimeError("404 parent not found")
            raise AssertionError(f"페이지 생성 실패 후 호출됨: {path}")

        with tempfile.TemporaryDirectory() as temp:
            rendered = Path(temp)
            (rendered / "images").mkdir()
            (rendered / "images" / "vg-1_action.jpg").write_bytes(b"img")
            with patch.object(exporter, "notion_request", side_effect=fake_request):
                with self.assertRaises(RuntimeError):
                    exporter.export_notion(data, rendered, "vid00000000", "bad-parent", "tok")
        self.assertEqual(["/pages"], calls)


if __name__ == "__main__":
    unittest.main()
