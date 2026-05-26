import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from clipping_ops_backend import database as db
from clipping_ops_backend.server import clean_reset, export_diagnostics, health, summary, validate_kit_artifacts, workspace_profile
from clipping_ops_backend.credentials import all_status


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

    def test_summary_counts_shape(self):
        payload = summary()
        self.assertIn("counts", payload)
        self.assertIn("review_kits", payload["counts"])

    def test_visible_surface_hides_demo_and_bad_feeder_clip(self):
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
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/lacy/clip/real-streamer-moment",
                "title": "Lacy actual stream moment",
                "provenance": "official_api_metadata",
                "risk_flags": ["selected_feeder_lacy"],
            }
        )
        visible = db.visible_clip_candidates()
        self.assertEqual([item["id"] for item in visible], [good_id])
        self.assertNotIn(local_clip, [item["id"] for item in visible])

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
        def create_green_lacy_kit(clip_id: str, rendered_epoch: int, kit_created_at: str) -> str:
            media = Path(self._tmp.name) / "source_media" / f"{clip_id}.mp4"
            media.parent.mkdir(parents=True, exist_ok=True)
            media.write_bytes(b"local source placeholder")
            candidate_id = db.upsert_clip_candidate(
                {
                    "id": clip_id,
                    "source_platform": "twitch",
                    "source_url": f"https://www.twitch.tv/lacy/clip/{clip_id}",
                    "title": "Lacy gets arrested live",
                    "local_media_path": str(media),
                    "clip_created_at": "2026-03-15T21:08:03Z",
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
                    f"transcript_{candidate_id}",
                    candidate_id,
                    "Lacy gets arrested.",
                    json.dumps([{"start": 0.0, "end": 1.8, "text": "Lacy gets arrested."}]),
                    json.dumps([
                        {"start": 0.0, "end": 0.4, "word": "Lacy"},
                        {"start": 0.4, "end": 0.8, "word": "arrested"},
                    ]),
                    db.utc_now(),
                ),
            )
            nomination_id = db.create_nomination(
                candidate_id,
                "Lacy gets arrested live",
                "Selected feeder clip with complete proof.",
                target_style=db.FINAL_PROOF_PROFILE,
                status="rendered_non_demo",
            )
            kit_dir = Path(self._tmp.name) / "render_kits" / clip_id
            kit_dir.mkdir(parents=True, exist_ok=True)
            for name, text in {
                "caption.txt": "Hook card: Lacy gets arrested live on stream\nSuggested post caption: Lacy on stream. #lacy\n",
                "transcript.txt": "Lacy gets arrested.\nWord timings:\n- 0.00-0.40: Lacy\n",
                "checklist.md": "- [x] Stored source URL exists for the clip candidate.\n",
                "source.md": f"- Source URL: https://www.twitch.tv/lacy/clip/{clip_id}\n- Source verification: `source_media_verified_local`\n- Local media: `{media}`\n\n## Lacy Brief Extract\nClip Requirements: Your clips must feature Lacy being arrested or being missing in action.\nCaption Requirements: Your caption/text overlay must mention Lacy's name. Your captions must use the hashtag: #lacy\n\n## Campaign Fit\n- Lacy requirement: feature Lacy being arrested or missing in action.\n- Matched terms: arrest\n",
                "risk.md": "- Campaign fit is backed by stored gate evidence and selected-feeder source rules.\n",
                "style_critique.md": "Status: green\nProfile: selected_feeder_final_v1\n",
                "render_text_manifest.json": json.dumps(
                    {
                        "profile": "selected_feeder_final_v1",
                        "rendered_text": {
                            "hook_card": "Lacy gets arrested live on stream",
                            "caption_beats": ["LACY ARRESTED"],
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
            for name in ("thumbnail.jpg", "contact_sheet.jpg"):
                (kit_dir / name).write_bytes(b"artifact")
            video = kit_dir / "review.mp4"
            video.write_bytes(b"artifact")
            os.utime(video, (rendered_epoch, rendered_epoch))
            kit_id = db.create_render_kit(
                nomination_id,
                "Lacy gets arrested live",
                video,
                kit_dir / "caption.txt",
                kit_dir / "transcript.txt",
                kit_dir / "checklist.md",
                kit_dir / "source.md",
                kit_dir / "risk.md",
                is_demo=False,
            )
            db.execute("UPDATE render_kits SET created_at=? WHERE id=?", (kit_created_at, kit_id))
            return kit_id

        older_id = create_green_lacy_kit("clip_rendered_old", 1_700_000_000, "2026-01-01T00:00:00+00:00")
        newer_id = create_green_lacy_kit("clip_rendered_new", 1_800_000_000, "2026-01-02T00:00:00+00:00")
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
                        "caption_beats": ["WE'RE PUSHING TOP SPEEDS"],
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(db._render_text_manifest_blockers(manifest), [])

        manifest.write_text(
            json.dumps(
                {
                    "rendered_text": {
                        "hook_card": "dd",
                        "source_badge": "TWITCH.TV/LACY",
                        "caption_beats": ["THIS IS WHAT YOU SUPPORTED"],
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("hook card" in item for item in db._render_text_manifest_blockers(manifest)))

    def test_final_proof_status_can_go_green_without_publish_approval(self):
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
                        "caption_beats": ["WAIT FOR THIS"],
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
        self.assertEqual(status["classification"], "green", status["blockers"])

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
        self.assertTrue(any("arrested/missing-in-action" in blocker or "#lacy" in blocker for blocker in status["blockers"]))


if __name__ == "__main__":
    unittest.main()
