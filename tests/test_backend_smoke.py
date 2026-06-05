import json
import os
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from clipping_ops_backend.caption_style import (
    CAPTION_AUDIO_SYNC_DELAY_SECONDS,
    CAPTION_MAX_WORD_GAP_SECONDS,
    CAPTION_MAX_WORD_SPAN_SECONDS,
    apply_caption_audio_sync_delay,
    caption_beat_violations,
    caption_center_y_for_source,
    caption_display_text,
    caption_start_for_group,
    caption_style_manifest,
    caption_text_quality_violations,
    clean_timed_words_for_caption,
    repair_timed_words_for_caption,
    timed_caption_groups,
)
from clipping_ops_backend import database as db
from clipping_ops_backend.server import clean_reset, export_diagnostics, health, summary, validate_kit_artifacts, workspace_profile
from clipping_ops_backend.credentials import all_status


def write_valid_review_video(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:d=0.12:r=30",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=20,
    )


class BackendSmokeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("CLIPPING_OPS_HOME")
        os.environ["CLIPPING_OPS_HOME"] = self._tmp.name
        db.init_db()

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("CLIPPING_OPS_HOME", None)
        else:
            os.environ["CLIPPING_OPS_HOME"] = self._old_home
        self._tmp.cleanup()

    def test_health_has_safety_gates(self):
        payload = health()
        self.assertEqual(payload["safety"]["autopublish"], "blocked")
        self.assertEqual(payload["safety"]["payout_submission"], "blocked")
        self.assertEqual(payload["safety"]["account_connection"], "blocked")
        self.assertEqual(payload["safety"]["account_rebrand"], "blocked")
        self.assertFalse(payload["production_green"])
        self.assertIn("ffmpeg", payload["checks"])

    def test_caption_style_uses_tiktok_sans_and_two_word_beats(self):
        manifest = caption_style_manifest()
        self.assertIn("TikTokSans", manifest["font_file"])
        self.assertTrue(Path(manifest["font_file"]).exists())
        self.assertEqual(manifest["max_words_per_line"], 2)
        self.assertEqual(manifest["max_lines_per_caption"], 1)
        self.assertEqual(manifest["max_words_on_screen"], 2)
        self.assertEqual(manifest["production_ab_variants"], ["A", "B", "D", "E"])
        self.assertEqual(manifest["default_campaign_variant"], "B")
        self.assertNotIn("C", manifest["production_ab_variants"])
        self.assertEqual(manifest["safe_band_top_y"], 1128)
        self.assertEqual(manifest["safe_band_bottom_y"], 1235)
        self.assertEqual(manifest["max_word_gap_seconds"], CAPTION_MAX_WORD_GAP_SECONDS)
        self.assertEqual(manifest["max_word_span_seconds"], CAPTION_MAX_WORD_SPAN_SECONDS)
        self.assertGreaterEqual(manifest["vertical_center_y"], manifest["safe_band_top_y"])
        self.assertLessEqual(manifest["vertical_center_y"], manifest["safe_band_bottom_y"])
        self.assertGreaterEqual(caption_center_y_for_source(360, 636), manifest["safe_band_top_y"])
        self.assertLessEqual(caption_center_y_for_source(360, 636), manifest["safe_band_bottom_y"])

        groups = timed_caption_groups(
            [
                {"word": "This", "start": 0.0, "end": 0.2},
                {"word": "is", "start": 0.2, "end": 0.4},
                {"word": "unbelievable", "start": 0.4, "end": 0.8},
                {"word": "right", "start": 0.8, "end": 1.0},
                {"word": "now", "start": 1.0, "end": 1.2},
            ]
        )
        self.assertEqual([" ".join(item["word"] for item in group) for group in groups], ["This is", "unbelievable", "right now"])
        paused_groups = timed_caption_groups(
            [
                {"word": "no", "start": 1.0, "end": 1.12},
                {"word": "shit", "start": 1.16, "end": 1.31},
                {"word": "gang", "start": 2.04, "end": 2.22},
            ]
        )
        self.assertEqual([" ".join(item["word"] for item in group) for group in paused_groups], ["no shit", "gang"])
        self.assertEqual(caption_beat_violations(["THIS IS", "UNBELIEVABLE", "RIGHT NOW"]), [])
        self.assertTrue(caption_beat_violations(["THIS IS WAY TOO MUCH"]))
        self.assertEqual(caption_text_quality_violations(["I'M GOOD", "STILL ISN'T", "SHIPPERS"]), [])
        self.assertTrue(caption_text_quality_violations(["AIN 'T", "DON DIDN", "SH IPPERS"]))
        self.assertEqual(caption_display_text("NO SHIT, gang."), "NO SHIT GANG")
        self.assertEqual(caption_display_text("n***a's who"), "N***A'S WHO")
        self.assertEqual(caption_beat_violations(["N***A'S WHO"]), [])
        self.assertGreaterEqual(caption_start_for_group(0.18, 2.13, "WHAT THE"), 1.84)
        self.assertLessEqual(caption_start_for_group(0.04, 0.39, "I SHOULD"), 0.12)
        delayed_start, delayed_end = apply_caption_audio_sync_delay(1.55, 2.11)
        self.assertAlmostEqual(delayed_start, 1.55 + CAPTION_AUDIO_SYNC_DELAY_SECONDS, places=3)
        self.assertAlmostEqual(delayed_end, 2.11 + CAPTION_AUDIO_SYNC_DELAY_SECONDS, places=3)

        repaired = repair_timed_words_for_caption(
            [
                {"word": "I", "start": 0.22, "end": 0.22},
                {"word": "ain", "start": 0.29, "end": 0.39},
                {"word": "'t", "start": 0.39, "end": 0.50},
                {"word": "Sil", "start": 5.51, "end": 5.64},
                {"word": "ky", "start": 5.71, "end": 5.83},
            ]
        )
        self.assertEqual([item["word"] for item in repaired], ["I", "ain't", "Silky"])
        self.assertGreater(repaired[0]["end"], repaired[0]["start"])
        long_span = repair_timed_words_for_caption([{"word": "shit", "start": 2.18, "end": 5.16}])
        self.assertLessEqual(long_span[0]["end"] - long_span[0]["start"], 0.26)
        self.assertAlmostEqual(long_span[0]["end"], 5.16, places=3)

    def test_ensemble_caption_beats_keep_visual_audio_delay(self):
        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_test"] = module
        spec.loader.exec_module(module)

        beats = module.caption_beats_from_transcript(
            {
                "provider": "ensemble_timestamp_consensus_v1",
                "segments_json": json.dumps(
                    [
                        {
                            "caption_beat": True,
                            "text": "NO SHIT",
                            "start": 1.0,
                            "end": 1.44,
                            "source_start": 0.92,
                            "source_end": 1.38,
                            "timing_mode": "ensemble_consensus",
                            "model_votes": 4,
                            "vote_spread_seconds": 0.08,
                        }
                    ]
                ),
            }
        )
        self.assertEqual(beats[0]["text"], "NO SHIT")
        self.assertAlmostEqual(beats[0]["start"], 1.0 + CAPTION_AUDIO_SYNC_DELAY_SECONDS, places=3)
        self.assertAlmostEqual(beats[0]["audio_sync_delay_seconds"], CAPTION_AUDIO_SYNC_DELAY_SECONDS, places=3)

    def test_top_hook_card_uses_reference_style_source_space_font(self):
        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_top_hook_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_top_hook_test"] = module
        spec.loader.exec_module(module)

        font_name = module.top_hook_card_font(34).getname()
        tiktok_bold = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "clipping_ops_backend"
            / "assets"
            / "fonts"
            / "TikTokSans36pt-Bold.ttf"
        )
        if tiktok_bold.exists():
            self.assertEqual(font_name, ("TikTok Sans", "Bold"))
        elif Path("/System/Library/Fonts/Avenir Next.ttc").exists():
            self.assertEqual(font_name, ("Avenir Next", "Demi Bold"))
        elif Path("/System/Library/Fonts/SFNS.ttf").exists():
            self.assertEqual(font_name, ("System Font", "Semibold"))
        else:
            self.assertEqual(font_name, ("TikTok Sans", "SemiBold"))

    def test_two_line_top_hook_uses_reference_width_card(self):
        from PIL import Image
        from script.audit_top_card_reference import measure_overlay

        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_top_card_width_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_top_card_width_test"] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "title_card.png"
            hook = module.headline_card(
                path,
                "Max got tired of Jason and Silky green screening his stream",
                "max",
            )
            self.assertIn("green screening", hook)
            metrics = measure_overlay(Image.open(path).convert("RGBA"))
            self.assertGreaterEqual(metrics["card_width"], 875)
            self.assertLessEqual(metrics["card_width"], 895)
            self.assertGreaterEqual(metrics["card_height"], 153)
            self.assertLessEqual(metrics["card_height"], 158)
            self.assertGreaterEqual(metrics["text_height"], 116)
            self.assertLessEqual(metrics["text_height"], 122)
            self.assertGreaterEqual(metrics["left_pad"], 34)
            self.assertLessEqual(metrics["left_pad"], 38)
            self.assertGreaterEqual(metrics["right_pad"], 33)
            self.assertLess(abs(metrics["card_center_x"] - 540), 4)

    def test_short_two_line_top_hook_uses_fit_width_card(self):
        from PIL import Image
        from script.audit_top_card_reference import measure_overlay

        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_top_card_fit_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_top_card_fit_test"] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "title_card.png"
            hook = module.headline_card(path, "Jason got tired of fake rumor math", "jasontheween")
            self.assertIn("fake rumor math", hook)
            metrics = measure_overlay(Image.open(path).convert("RGBA"))
            self.assertGreaterEqual(metrics["card_width"], 685)
            self.assertLessEqual(metrics["card_width"], 760)
            self.assertGreaterEqual(metrics["left_pad"], 34)
            self.assertLessEqual(metrics["left_pad"], 38)
            self.assertLess(abs(metrics["card_center_x"] - 540), 4)

    def test_top_hook_does_not_append_fake_stream_suffix(self):
        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_suffix_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_suffix_test"] = module
        spec.loader.exec_module(module)

        hook = module.reference_top_hook_text("Max got Lucki talking about turning thirty")
        self.assertEqual(hook, "Max got Lucki talking about turning thirty 🤣🤣")
        self.assertNotIn("on stream", hook.lower())

    def test_top_hook_reference_audit_passes_when_reference_exists(self):
        root = Path(__file__).resolve().parents[1]
        reference = root / "artifacts" / "review-kit-audit" / "top-typography-audit" / "reference-frame-1080.jpg"
        if not reference.exists():
            self.skipTest("local TikTok reference frame is not present")
        result = subprocess.run(
            [sys.executable, str(root / "script" / "audit_top_card_reference.py")],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_caption_timing_cleaner_drops_vtt_boundary_slivers(self):
        words = [
            {"word": "It's", "start": 0.0, "end": 0.02},
            {"word": "growing", "start": 0.02, "end": 0.03},
            {"word": "in", "start": 0.03, "end": 0.05},
            {"word": "the", "start": 0.05, "end": 0.07},
            {"word": "stock", "start": 0.07, "end": 0.08},
            {"word": "market.", "start": 0.08, "end": 0.10},
            {"word": "It's", "start": 0.0, "end": 0.20},
            {"word": "growing", "start": 0.20, "end": 0.39},
            {"word": "outside", "start": 0.39, "end": 0.58},
            {"word": "of", "start": 0.58, "end": 0.77},
        ]
        cleaned = clean_timed_words_for_caption(words, provider="youtube_vtt_campaign_subtitles")
        self.assertEqual([item["word"] for item in cleaned[:4]], ["It's", "growing", "outside", "of"])
        self.assertTrue(all(item["end"] - item["start"] >= 0.12 for item in cleaned))
        self.assertEqual([item["start"] for item in cleaned], sorted(item["start"] for item in cleaned))

    def test_summary_counts_shape(self):
        payload = summary()
        self.assertIn("counts", payload)
        self.assertIn("review_kits", payload["counts"])

    def test_hermes_job_intent_lifecycle_and_proof(self):
        job = db.create_job_intent(
            "build_campaign_reviews",
            {"campaign_slug": "kalshi", "limit": 5, "style": db.CAMPAIGN_SHORT_PROFILE},
            campaign_slug="kalshi",
            requested_by="gui",
        )
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["intent"], "build_campaign_reviews")
        self.assertEqual(job["campaign_slug"], "kalshi")
        self.assertFalse(db.hermes_native_execution_proof()["ok"])

        claimed = db.claim_job(job["id"], "hermes-dispatcher", profile="default")
        self.assertEqual(claimed["status"], "claimed")
        self.assertTrue(claimed["claim_token"].startswith("claim_"))

        running = db.heartbeat_job(claimed["id"], claimed["claim_token"], stage="rendering", progress=42)
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["stage"], "rendering")

        done = db.complete_job(claimed["id"], claimed["claim_token"], result={"status": "succeeded"}, logs="ok")
        self.assertEqual(done["status"], "succeeded")
        proof = db.hermes_native_execution_proof()
        self.assertTrue(proof["ok"])
        self.assertEqual(proof["job_id"], job["id"])

    def test_hermes_job_dedupe_and_cancel(self):
        first = db.create_job_intent("refresh_campaign_project", {"campaign_slug": "kalshi"}, campaign_slug="kalshi")
        second = db.create_job_intent("refresh_campaign_project", {"campaign_slug": "kalshi"}, campaign_slug="kalshi")
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["deduped"])

        cancelled = db.cancel_job(first["id"], actor="test")
        self.assertEqual(cancelled["status"], "cancelled")
        replacement = db.create_job_intent("refresh_campaign_project", {"campaign_slug": "kalshi"}, campaign_slug="kalshi")
        self.assertNotEqual(first["id"], replacement["id"])

    def test_visible_surface_hides_demo_and_old_feeder_clip(self):
        local_clip = db.upsert_clip(Path(self._tmp.name) / "demo.mp4", "Demo Review Kit", 3.0)
        db.upsert_clip_candidate(
            {
                "id": "ignored",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/lacy/clip/FrigidGoodAubergineTooSpicy-JP0AxQ7qqJoUa8K6",
                "title": "wild",
                "provenance": "yt_dlp_fallback",
                "risk_flags": ["selected_feeder_lacy", "source_download_verified"],
            }
        )
        good_id = db.upsert_clip_candidate(
            {
                "campaign_slug": "yourrage",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/yourragegaming/clip/active-contract",
                "title": "YourRAGE active streamer moment",
                "clip_created_at": "2026-05-08T21:08:03Z",
                "provenance": "official_api_metadata",
                "risk_flags": ["campaign_project_yourrage", "selected_feeder_yourrage"],
            }
        )
        visible = db.visible_clip_candidates()
        self.assertEqual([item["id"] for item in visible], [good_id])
        self.assertNotIn(local_clip, [item["id"] for item in visible])

    def test_editorial_gate_rejects_low_view_overlong_split_facecam(self):
        clip_id = db.upsert_clip_candidate(
            {
                "id": "clip_editorial_bad",
                "campaign_slug": "yourrage",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/yourragegaming/clip/editorial-bad",
                "title": "a",
                "duration": 59.9,
                "view_count": 99,
                "provenance": "official_api_metadata",
                "risk_flags": ["campaign_project_yourrage", "selected_feeder_yourrage"],
            }
        )
        clip = db.one("SELECT * FROM clip_candidates WHERE id = ?", (clip_id,))
        kit_dir = Path(self._tmp.name) / "render_kits" / "editorial_bad"
        kit_dir.mkdir(parents=True, exist_ok=True)
        (kit_dir / "render_text_manifest.json").write_text(
            json.dumps({"rendered_text": {"composition": {"mode": "streamer_split_facecam_top"}}}),
            encoding="utf-8",
        )
        (kit_dir / "editorial_review.json").write_text(json.dumps({"status": "green"}), encoding="utf-8")
        gate = db.editorial_review_for_rendered_kit(clip, kit_dir, "yourrage")
        self.assertEqual(gate["status"], "red")
        self.assertTrue(any("editorial floor" in blocker for blocker in gate["blockers"]))
        self.assertTrue(any("facecam-top" in blocker for blocker in gate["blockers"]))

    def test_render_kit_enrichment_exposes_clip_broadcast_time(self):
        clip_id = db.upsert_clip_candidate(
            {
                "id": "clip_time_contract",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/lacy/clip/time-contract",
                "title": "Lacy timestamp contract",
                "duration": 12.5,
                "view_count": 123456,
                "clip_created_at": "2026-03-15T21:08:03Z",
                "provenance": "official_api_metadata",
                "risk_flags": ["selected_feeder_lacy"],
            }
        )
        nomination_id = db.create_nomination(
            clip_id,
            "Lacy timestamp contract",
            "Clip metadata should be visible in Review Kits.",
            target_style=db.FINAL_PROOF_PROFILE,
            status="rendered_non_demo",
        )

        enriched = db.enrich_render_kit_with_clip_metadata({"id": "kit_time_contract", "nomination_id": nomination_id})
        self.assertEqual(enriched["clip_id"], clip_id)
        self.assertEqual(enriched["clip_created_at"], "2026-03-15T21:08:03Z")
        self.assertEqual(enriched["clip_source_platform"], "twitch")
        self.assertEqual(enriched["clip_view_count"], 123456)

    def test_render_kit_enrichment_exposes_rendered_at_and_sorts_descending(self):
        def create_green_campaign_kit(clip_id: str, rendered_epoch: int, kit_created_at: str) -> str:
            media = Path(self._tmp.name) / "source_media" / f"{clip_id}.mp4"
            media.parent.mkdir(parents=True, exist_ok=True)
            media.write_bytes(b"local source placeholder")
            candidate_id = db.upsert_clip_candidate(
                {
                    "id": clip_id,
                    "campaign_slug": "yourrage",
                    "source_platform": "twitch",
                    "source_url": f"https://www.twitch.tv/yourragegaming/clip/{clip_id}",
                    "title": "YourRAGE chat loses it",
                    "duration": 30.0,
                    "view_count": 2200,
                    "local_media_path": str(media),
                    "clip_created_at": "2026-05-15T21:08:03Z",
                    "provenance": "official_api_metadata",
                    "risk_flags": ["campaign_project_yourrage", "selected_feeder_yourrage", "source_media_verified_local"],
                }
            )
            db.create_campaign_evidence(
                {
                    "campaign_id": "yourrage",
                    "evidence_type": "campaign_rules",
                    "title": "YourRAGE campaign rules",
                    "source_url": "https://clipping.net/dashboard/campaigns/yourrage-x-clipping",
                    "extracted_text": "Requirements: None. Source route: Twitch handle yourragegaming. Caption Requirements: None.",
                    "confidence": 0.9,
                }
            )
            db.execute(
                """
                INSERT INTO transcripts
                  (id, clip_candidate_id, provider, language, confidence, full_text, segments_json, word_timings_json, status, created_at)
                VALUES (?, ?, 'misterwhisper-local', 'en', 0.91, ?, ?, ?, 'succeeded', ?)
                """,
                (
                    f"transcript_{candidate_id}",
                    candidate_id,
                    "Chat lost it when the stream changed.",
                    json.dumps([{"start": 0.0, "end": 2.2, "text": "Chat lost it when the stream changed."}]),
                    json.dumps([
                        {"start": 0.0, "end": 0.4, "word": "Chat"},
                        {"start": 0.4, "end": 0.8, "word": "lost"},
                        {"start": 0.8, "end": 1.2, "word": "it"},
                    ]),
                    db.utc_now(),
                ),
            )
            nomination_id = db.create_nomination(
                candidate_id,
                "YourRAGE chat loses it",
                "Campaign clip with complete source proof.",
                target_style=db.CAMPAIGN_SHORT_PROFILE,
                status="rendered_non_demo",
                campaign_slug="yourrage",
            )
            kit_dir = Path(self._tmp.name) / "render_kits" / clip_id
            kit_dir.mkdir(parents=True, exist_ok=True)
            for name, text in {
                "caption.txt": "Hook card: Chat lost it during the stream\n",
                "transcript.txt": "Chat lost it when the stream changed.\nWord timings:\n- 0.00-0.40: Chat\n",
                "checklist.md": "- [x] Stored source URL exists for the clip candidate.\n",
                "source.md": f"- Source URL: https://www.twitch.tv/yourragegaming/clip/{clip_id}\n- Source verification: `source_media_verified_local`\n- Local media: `{media}`\n- Campaign: `YourRAGE`\n\n## Stored Campaign Rules\n- `yourrage`: https://clipping.net/dashboard/campaigns/yourrage-x-clipping\n",
                "risk.md": "- This is not approval to publish.\n- Campaign fit is backed by stored rules and local source evidence.\n",
                "style_critique.md": "Status: green\nProfile: campaign_short_final_v1\n",
                "render_text_manifest.json": json.dumps(
                    {
                        "profile": "campaign_short_final_v1",
                        "rendered_text": {
                            "hook_card": "Chat lost it during stream",
                            "caption_beats": ["CHAT LOST", "IT"],
                            "composition": {"mode": "streamer_center_preserve_source"},
                        },
                    }
                ),
                "editorial_review.json": json.dumps(
                    {
                        "status": "green",
                        "blockers": [],
                        "warnings": [],
                        "clip_id": candidate_id,
                        "campaign_slug": "yourrage",
                        "composition_mode": "streamer_center_preserve_source",
                    }
                ),
                "ffprobe.json": json.dumps(
                    {
                        "streams": [
                            {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                            {"codec_type": "audio", "codec_name": "aac"},
                        ]
                    }
                ),
            }.items():
                (kit_dir / name).write_text(text, encoding="utf-8")
            for name in ("thumbnail.jpg", "contact_sheet.jpg"):
                (kit_dir / name).write_bytes(b"artifact")
            video = kit_dir / "review.mp4"
            write_valid_review_video(video)
            os.utime(video, (rendered_epoch, rendered_epoch))
            kit_id = db.create_render_kit(
                nomination_id,
                "YourRAGE chat loses it",
                video,
                kit_dir / "caption.txt",
                kit_dir / "transcript.txt",
                kit_dir / "checklist.md",
                kit_dir / "source.md",
                kit_dir / "risk.md",
                is_demo=False,
                campaign_slug="yourrage",
            )
            db.execute("UPDATE render_kits SET created_at=? WHERE id=?", (kit_created_at, kit_id))
            return kit_id

        older_id = create_green_campaign_kit("clip_rendered_old", 1_700_000_000, "2026-01-01T00:00:00+00:00")
        newer_id = create_green_campaign_kit("clip_rendered_new", 1_800_000_000, "2026-01-02T00:00:00+00:00")
        visible = db.visible_render_kits()
        self.assertEqual([item["id"] for item in visible[:2]], [newer_id, older_id])
        self.assertEqual(
            visible[0]["rendered_at"],
            datetime.fromtimestamp(1_800_000_000, timezone.utc).isoformat(),
        )

    def test_auth_status_shape(self):
        payload = all_status()
        self.assertIn("twitch", payload["providers"])
        self.assertIn("kick", payload["providers"])
        self.assertIn("required_redirects", payload)
        raw = json.dumps(payload).lower()
        self.assertNotIn("client_secret", raw.replace('"client_secret": "configured"', ""))
        self.assertNotIn("access_token", raw)

    def test_no_key_mode_blocks_credential_reads_and_refresh(self):
        os.environ["CLIPPING_OPS_NO_KEY"] = "1"
        from clipping_ops_backend import credentials

        payload = credentials.all_status()
        self.assertTrue(payload["no_key_mode"])
        self.assertFalse(payload["providers"]["twitch"]["ok"])
        self.assertEqual(credentials.refresh_app_token("twitch")["status"], "blocked")

    def test_readiness_separates_demo_from_campaign(self):
        payload = db.readiness_report()
        self.assertEqual(payload["overall"], "red")
        self.assertIn("milestones", payload)
        self.assertFalse(payload["milestones"]["customer_ship_ready"]["ready"])
        gate = next(item for item in payload["features"] if item["name"] == "Campaign research gate")
        self.assertEqual(gate["status"], "red")
        batch = next(item for item in payload["features"] if item["name"] == "Campaign review batch")
        self.assertEqual(batch["status"], "red")

    def test_campaign_registry_excludes_no_source_content_gen_projects(self):
        projects = db.campaign_project_records()
        self.assertEqual([project["slug"] for project in projects], ["yourrage", "plaqueboymax", "jasontheween"])
        self.assertTrue(all(project["review_target_count"] == 5 for project in projects))
        self.assertTrue(projects[0]["campaign_url"].endswith("/yourrage-x-clipping"))
        self.assertTrue(projects[1]["campaign_url"].endswith("/plaqueboymax-x-clipping"))
        self.assertTrue(projects[2]["campaign_url"].endswith("/jasontheween-x-clipping"))
        self.assertFalse(projects[0]["watermark_required"])
        self.assertTrue(projects[1]["watermark_required"])
        self.assertTrue(projects[2]["watermark_required"])
        self.assertIn("watermark", " ".join(projects[1]["blockers"]).lower())
        self.assertIn("watermark", " ".join(projects[2]["blockers"]).lower())
        excluded = db.excluded_campaign_projects()
        excluded_slugs = [item["slug"] for item in excluded]
        self.assertIn("doublelift", excluded_slugs)
        self.assertIn("kalshi", excluded_slugs)
        self.assertIn("dunkman", excluded_slugs)
        self.assertIn("haste", excluded_slugs)
        haste = next(item for item in excluded if item["slug"] == "haste")
        self.assertIn("content generation", haste["reason"])

    def test_haste_is_excluded_without_linked_media(self):
        from clipping_ops_backend.server import discover_campaign_sources, build_campaign_reviews

        discovery = discover_campaign_sources("haste")
        self.assertEqual(discovery["status"], "excluded")
        self.assertIn("content generation", " ".join(discovery["blockers"]).lower())
        build = build_campaign_reviews("haste", limit=5, style=db.CAMPAIGN_SHORT_PROFILE)
        self.assertEqual(build["status"], "excluded")
        self.assertIn("content generation", build["blocker"].lower())

    def test_watermark_campaign_blocks_render_until_asset_installed(self):
        from clipping_ops_backend.server import build_campaign_reviews

        build = build_campaign_reviews("plaqueboymax", limit=1, style=db.CAMPAIGN_SHORT_PROFILE)
        self.assertEqual(build["status"], "blocked")
        self.assertIn("watermark", build["blocker"].lower())

    def test_old_lacy_kits_do_not_count_toward_three_campaign_batch(self):
        batch = db.three_campaign_review_batch_status()
        self.assertFalse(batch["ready"])
        self.assertEqual(batch["approved_total"], 0)
        self.assertTrue(any("YourRAGE" in blocker for blocker in batch["blockers"]))
        self.assertTrue(any("PlaqueBoyMax" in blocker for blocker in batch["blockers"]))
        self.assertTrue(any("JasonTheWeen" in blocker for blocker in batch["blockers"]))

    def test_render_roots_keep_demo_out_of_production_root(self):
        self.assertNotEqual(db.render_root(), db.demo_render_root())
        self.assertIn("render_kits", str(db.render_root()))
        self.assertIn("demo_render_kits", str(db.demo_render_root()))

    def test_campaign_gate_requires_evidence_and_routes(self):
        from clipping_ops_backend.server import run_campaign_gate

        gate = run_campaign_gate()
        self.assertEqual(gate["status"], "blocked")
        self.assertIn("campaign", gate["blocker"].lower())

    def test_platform_and_route_records_are_redacted(self):
        check_id = db.record_platform_check(
            "twitch",
            "/helix/users",
            "succeeded",
            200,
            request_summary="GET /helix/users",
            response_excerpt='{"data":[]}',
            rate_limit_remaining="799",
        )
        route = db.upsert_source_route(
            {
                "platform": "twitch",
                "creator_handle": "example",
                "route_type": "official_api",
                "availability_status": "reachable",
                "latest_check_id": check_id,
            }
        )
        self.assertEqual(route["availability_status"], "reachable")
        payload = json.dumps(db.rows("SELECT * FROM platform_api_checks"))
        self.assertNotIn("Bearer ", payload)

    def test_kit_validation_requires_all_artifacts(self):
        kit = {
            "review_video_path": str(Path(self._tmp.name) / "missing.mp4"),
            "caption_path": "",
            "transcript_path": "",
            "checklist_path": "",
            "source_path": "",
            "risk_path": "",
        }
        ok, detail = validate_kit_artifacts(kit)
        self.assertFalse(ok)
        self.assertIn("missing artifact", detail)

    def test_workspace_profile_and_diagnostics_export_are_no_secret(self):
        profile = workspace_profile()
        self.assertFalse(profile["billing_enabled"])
        result = export_diagnostics()
        self.assertEqual(result["status"], "succeeded")
        archive = Path(result["path"])
        self.assertTrue(archive.exists())
        self.assertEqual(archive.suffix, ".zip")

    def test_clean_reset_requires_exact_confirmation(self):
        blocked = clean_reset({"confirm": "reset"})
        self.assertEqual(blocked["status"], "blocked")

    def test_render_text_manifest_blocks_internal_burned_in_labels(self):
        manifest = Path(self._tmp.name) / "render_text_manifest.json"
        manifest.write_text(
            json.dumps({"rendered_text": {"hook_card": "SELECTED FEEDER REVIEW | @lacy", "caption_beats": ["WAIT FOR IT"]}}),
            encoding="utf-8",
        )
        blockers = db._render_text_manifest_blockers(manifest)
        self.assertTrue(any("selected feeder" in item for item in blockers))

        manifest.write_text(
            json.dumps(
                {
                    "rendered_text": {
                        "hook_card": "Lacy was TEXTING and DRIVING without a SEATBELT",
                        "source_badge": "TWITCH.TV/LACY",
                        "caption_beats": ["TOP SPEEDS", "RIGHT NOW"],
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(db._render_text_manifest_blockers(manifest), [])

        manifest.write_text(
            json.dumps({"rendered_text": {"caption_beats": ["WE'RE PUSHING TOP SPEEDS"]}}),
            encoding="utf-8",
        )
        self.assertTrue(any("two-word" in item for item in db._render_text_manifest_blockers(manifest)))

        manifest.write_text(
            json.dumps(
                {
                    "caption_only": True,
                    "rendered_text": {
                        "layout": "caption_only",
                        "hook_card_visible": False,
                        "hook_card": "",
                        "source_badge_visible": False,
                        "source_badge": "",
                        "caption_beats": ["THIS IS", "WHAT YOU", "SUPPORTED", "WAIT FOR", "IT NOW"],
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(db._render_text_manifest_blockers(manifest), [])

        manifest.write_text(
            json.dumps(
                {
                    "profile": db.CAMPAIGN_SHORT_PROFILE,
                    "caption_only": True,
                    "rendered_text": {
                        "layout": "caption_only",
                        "hook_card_visible": False,
                        "hook_card": "",
                        "caption_beats": ["THIS IS", "WHAT YOU", "SUPPORTED", "WAIT FOR", "IT NOW"],
                    },
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("top summary hook" in item for item in db._render_text_manifest_blockers(manifest)))

        manifest.write_text(
            json.dumps(
                {
                    "profile": db.CAMPAIGN_SHORT_PROFILE,
                    "caption_only": False,
                    "rendered_text": {
                        "layout": "summary_hook_caption",
                        "hook_card_visible": True,
                        "hook_card": "Max got tired of Jason and Silky green screening his stream",
                        "hook_card_persistent": True,
                        "caption_beats": ["THIS IS", "WHAT YOU", "SUPPORTED", "WAIT FOR", "IT NOW"],
                    },
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(db._render_text_manifest_blockers(manifest), [])

        manifest.write_text(
            json.dumps(
                {
                    "caption_only": True,
                    "rendered_text": {
                        "layout": "caption_only",
                        "hook_card_visible": False,
                        "hook_card": "",
                        "caption_beats": ["DD"],
                    },
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("caption-only" in item for item in db._render_text_manifest_blockers(manifest)))

    def test_demoted_lacy_final_proof_cannot_go_green_even_with_complete_artifacts(self):
        media = Path(self._tmp.name) / "source_media" / "clip_final.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"local source placeholder")
        clip_id = db.upsert_clip_candidate(
            {
                "id": "clip_final",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/lacy/clip/clean-final",
                "title": "Lacy clean final",
                "local_media_path": str(media),
                "provenance": "official_api_metadata",
                "risk_flags": ["selected_feeder_lacy", "source_media_verified_local", db.LACY_CAMPAIGN_FIT_FLAG],
            }
        )
        db.create_campaign_evidence(
            {
                "campaign_id": "lacy",
                "evidence_type": "campaign_rules",
                "title": "Lacy campaign rules",
                "source_url": "https://clipping.example/lacy",
                "extracted_text": "Clip Requirements: Your clips must feature Lacy being arrested or being missing in action. Caption Requirements: Your caption/text overlay must mention Lacy's name. Your captions must use the hashtag: #lacy",
                "confidence": 0.9,
            }
        )
        db.execute(
            """
            INSERT INTO transcripts
              (id, clip_candidate_id, provider, language, confidence, full_text, segments_json, word_timings_json, status, created_at)
            VALUES (?, ?, 'misterwhisper-local', 'en', 0.91, ?, ?, ?, 'succeeded', ?)
            """,
            (
                "transcript_final",
                clip_id,
                "Wait for this moment.",
                json.dumps([{"start": 0.0, "end": 1.8, "text": "Wait for this moment."}]),
                json.dumps([
                    {"start": 0.0, "end": 0.4, "word": "Wait"},
                    {"start": 0.4, "end": 0.8, "word": "for"},
                    {"start": 0.8, "end": 1.2, "word": "this"},
                    {"start": 1.2, "end": 1.8, "word": "moment"},
                ]),
                db.utc_now(),
            ),
        )
        nomination_id = db.create_nomination(
            clip_id,
            "Lacy clean final",
            "Selected feeder clip with complete proof.",
            target_style=db.FINAL_PROOF_PROFILE,
            status="rendered_non_demo",
        )
        kit_dir = Path(self._tmp.name) / "render_kits" / "20260524-source-render-lacy-clip_final"
        kit_dir.mkdir(parents=True, exist_ok=True)
        for name, text in {
            "caption.txt": "Hook card: Lacy gets arrested live on stream\nSuggested post caption: Lacy on stream. #lacy\n",
            "transcript.txt": "Wait for this moment.\nWord timings:\n- 0.00-0.40: Wait\n",
            "checklist.md": "- [x] Stored source URL exists for the clip candidate.\n- [ ] Ready-to-post approval granted.\n",
            "source.md": f"- Source URL: https://www.twitch.tv/lacy/clip/clean-final\n- Source verification: `source_media_verified_local`\n- Local media: `{media}`\n\n## Lacy Brief Extract\nClip Requirements: Your clips must feature Lacy being arrested or being missing in action.\nCaption Requirements: Your caption/text overlay must mention Lacy's name. Your captions must use the hashtag: #lacy\n\n## Campaign Fit\n- Lacy requirement: feature Lacy being arrested or missing in action.\n- Matched terms: arrest\n",
            "risk.md": "- This is not approval to publish.\n- Campaign fit is backed by stored gate evidence and selected-feeder source rules.\n",
            "style_critique.md": "Status: green\nProfile: selected_feeder_final_v1\n",
            "render_text_manifest.json": json.dumps(
                {
                    "profile": "selected_feeder_final_v1",
                    "rendered_text": {
                        "hook_card": "Lacy gets arrested live on stream",
                        "source_badge": "TWITCH.TV/LACY",
                        "caption_beats": ["WAIT FOR", "THIS"],
                    },
                }
            ),
            "ffprobe.json": json.dumps(
                {
                    "streams": [
                        {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                        {"codec_type": "audio", "codec_name": "aac"},
                    ]
                }
            ),
        }.items():
            (kit_dir / name).write_text(text, encoding="utf-8")
        write_valid_review_video(kit_dir / "review.mp4")
        for name in ("thumbnail.jpg", "contact_sheet.jpg"):
            (kit_dir / name).write_bytes(b"artifact")
        kit_id = db.create_render_kit(
            nomination_id,
            "Lacy clean final",
            kit_dir / "review.mp4",
            kit_dir / "caption.txt",
            kit_dir / "transcript.txt",
            kit_dir / "checklist.md",
            kit_dir / "source.md",
            kit_dir / "risk.md",
            is_demo=False,
        )
        kit = db.one("SELECT * FROM render_kits WHERE id = ?", (kit_id,))
        status = db.production_feeder_kit_status(kit)
        self.assertNotEqual(status["classification"], "green", status["blockers"])
        self.assertTrue(any("Lacy is excluded" in blocker for blocker in status["blockers"]))

    def test_lacy_final_proof_requires_campaign_theme_and_hashtag(self):
        media = Path(self._tmp.name) / "source_media" / "clip_wrong_lacy.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"local source placeholder")
        clip_id = db.upsert_clip_candidate(
            {
                "id": "clip_wrong_lacy",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/lacy/clip/wrong-theme",
                "title": "Lacy talks about money",
                "local_media_path": str(media),
                "provenance": "official_api_metadata",
                "risk_flags": ["selected_feeder_lacy", "source_media_verified_local"],
            }
        )
        db.create_campaign_evidence(
            {
                "campaign_id": "lacy",
                "evidence_type": "campaign_rules",
                "title": "Lacy campaign rules",
                "source_url": "https://clipping.example/lacy",
                "extracted_text": "Clip Requirements: Your clips must feature Lacy being arrested or being missing in action. Caption Requirements: Your caption/text overlay must mention Lacy's name. Your captions must use the hashtag: #lacy",
                "confidence": 0.9,
            }
        )
        db.execute(
            """
            INSERT INTO transcripts
              (id, clip_candidate_id, provider, language, confidence, full_text, segments_json, word_timings_json, status, created_at)
            VALUES (?, ?, 'misterwhisper-local', 'en', 0.91, ?, ?, ?, 'succeeded', ?)
            """,
            (
                "transcript_wrong_lacy",
                clip_id,
                "Lacy talks about money.",
                json.dumps([{"start": 0.0, "end": 1.8, "text": "Lacy talks about money."}]),
                json.dumps([
                    {"start": 0.0, "end": 0.4, "word": "Lacy"},
                    {"start": 0.4, "end": 0.8, "word": "talks"},
                ]),
                db.utc_now(),
            ),
        )
        nomination_id = db.create_nomination(
            clip_id,
            "Lacy talks about money",
            "Selected feeder clip with complete proof.",
            target_style=db.FINAL_PROOF_PROFILE,
            status="rendered_non_demo",
        )
        kit_dir = Path(self._tmp.name) / "render_kits" / "20260524-source-render-lacy-wrong"
        kit_dir.mkdir(parents=True, exist_ok=True)
        for name, text in {
            "caption.txt": "Hook card: Lacy talks about money\n",
            "transcript.txt": "Lacy talks about money.\nWord timings:\n- 0.00-0.40: Lacy\n",
            "checklist.md": "- [x] Stored source URL exists for the clip candidate.\n- [ ] Ready-to-post approval granted.\n",
            "source.md": f"- Source URL: https://www.twitch.tv/lacy/clip/wrong-theme\n- Source verification: `source_media_verified_local`\n- Local media: `{media}`\n",
            "risk.md": "- This is not approval to publish.\n",
            "style_critique.md": "Status: green\nProfile: selected_feeder_final_v1\n",
            "render_text_manifest.json": json.dumps(
                {
                    "profile": "selected_feeder_final_v1",
                    "rendered_text": {
                        "hook_card": "Lacy talks about money",
                        "caption_beats": ["LACY TALKS"],
                    },
                }
            ),
            "ffprobe.json": json.dumps(
                {
                    "streams": [
                        {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                        {"codec_type": "audio", "codec_name": "aac"},
                    ]
                }
            ),
        }.items():
            (kit_dir / name).write_text(text, encoding="utf-8")
        for name in ("review.mp4", "thumbnail.jpg", "contact_sheet.jpg"):
            (kit_dir / name).write_bytes(b"artifact")
        kit_id = db.create_render_kit(
            nomination_id,
            "Lacy talks about money",
            kit_dir / "review.mp4",
            kit_dir / "caption.txt",
            kit_dir / "transcript.txt",
            kit_dir / "checklist.md",
            kit_dir / "source.md",
            kit_dir / "risk.md",
            is_demo=False,
        )
        kit = db.one("SELECT * FROM render_kits WHERE id = ?", (kit_id,))
        status = db.production_feeder_kit_status(kit)
        self.assertNotEqual(status["classification"], "green")
        self.assertTrue(any("Lacy is excluded" in blocker for blocker in status["blockers"]))


if __name__ == "__main__":
    unittest.main()
