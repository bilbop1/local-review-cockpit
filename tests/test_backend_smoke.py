import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

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
from clipping_ops_backend import publishing
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
        self.assertEqual(payload["safety"]["autopublish"], "locked_until_approved_confirmed")
        self.assertEqual(payload["safety"]["payout_submission"], "blocked")
        self.assertEqual(payload["safety"]["account_connection"], "blocked")
        self.assertEqual(payload["safety"]["account_rebrand"], "blocked")
        self.assertFalse(payload["production_green"])
        self.assertIn("ffmpeg", payload["checks"])
        self.assertIn("publish", payload)

    def make_publishable_kit(self, *, approved=True, is_demo=False) -> str:
        suffix = db.new_id("pubtest")
        clip_identifier = f"clip_publish_ready_{suffix}"
        media = Path(self._tmp.name) / "source_media" / f"{suffix}.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"source proof")
        clip_id = db.upsert_clip_candidate(
            {
                "id": clip_identifier,
                "campaign_slug": "yourrage",
                "source_platform": "twitch",
                "source_url": f"https://www.twitch.tv/yourragegaming/clip/{suffix}",
                "title": "YourRAGE publish ready",
                "duration": 21.0,
                "view_count": 2500,
                "local_media_path": str(media),
                "clip_created_at": "2026-05-15T21:08:03Z",
                "provenance": "official_api_metadata",
                "risk_flags": ["campaign_project_yourrage", "source_media_verified_local", "selected_feeder_yourragegaming"],
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
                f"transcript_{clip_id}",
                clip_id,
                "YourRAGE had chat crying when the stream changed.",
                json.dumps([{"start": 0.0, "end": 2.2, "text": "YourRAGE had chat crying when the stream changed."}]),
                json.dumps([
                    {"start": 0.0, "end": 0.4, "word": "YourRAGE"},
                    {"start": 0.4, "end": 0.8, "word": "had"},
                    {"start": 0.8, "end": 1.2, "word": "chat"},
                    {"start": 1.2, "end": 1.6, "word": "crying"},
                ]),
                db.utc_now(),
            ),
        )
        nomination_id = db.create_nomination(
            clip_id,
            "YourRAGE publish ready",
            "Approved review kit for publish dry-run tests.",
            target_style=db.CAMPAIGN_SHORT_PROFILE,
            status="rendered_non_demo",
            campaign_slug="yourrage",
        )
        kit_dir = Path(self._tmp.name) / "render_kits" / f"publish-ready-{suffix}-{'demo' if is_demo else 'campaign'}"
        kit_dir.mkdir(parents=True, exist_ok=True)
        for name, text in {
            "caption.txt": "Hook card: YourRAGE had chat crying\nSuggested post caption: YourRAGE had chat crying 😂 #yourrage\n",
            "transcript.txt": "YourRAGE had chat crying.\nWord timings:\n- 0.00-0.30: YourRAGE\n",
            "checklist.md": "- [x] Stored source URL exists for the clip candidate.\n",
            "source.md": f"- Source URL: https://www.twitch.tv/yourragegaming/clip/{suffix}\n- Source verification: `source_media_verified_local`\n- Local media: `{media}`\n",
            "risk.md": "- Publishing requires final confirmation.\n",
            "style_critique.md": "Status: green\nProfile: campaign_short_final_v1\n",
            "render_text_manifest.json": json.dumps(
                {
                    "profile": "campaign_short_final_v1",
                    "rendered_text": {
                        "layout": "summary_hook_caption",
                        "hook_card": "YourRAGE had chat fully crying",
                        "hook_card_visible": True,
                        "caption_beats": ["CHAT LOST", "STREAM WILD"],
                        "caption_timeline": [
                            {
                                "text": "CHAT LOST",
                                "start": 0.0,
                                "end": 1.0,
                                "timing_mode": "ensemble_consensus",
                                "model_votes": 3,
                                "vote_spread_seconds": 0.2,
                            },
                            {
                                "text": "STREAM WILD",
                                "start": 1.1,
                                "end": 2.1,
                                "timing_mode": "ensemble_consensus",
                                "model_votes": 3,
                                "vote_spread_seconds": 0.2,
                            },
                        ],
                        "composition": {"mode": "streamer_center_preserve_source"},
                    },
                }
            ),
            "editorial_review.json": json.dumps(
                {
                    "status": "green",
                    "blockers": [],
                    "warnings": [],
                    "thresholds": {"quota_recovery": False},
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
        write_valid_review_video(kit_dir / "review.mp4")
        kit_id = db.create_render_kit(
            nomination_id,
            "YourRAGE publish ready",
            kit_dir / "review.mp4",
            kit_dir / "caption.txt",
            kit_dir / "transcript.txt",
            kit_dir / "checklist.md",
            kit_dir / "source.md",
            kit_dir / "risk.md",
            is_demo=is_demo,
            campaign_slug="yourrage",
        )
        if approved:
            db.execute("UPDATE render_kits SET review_status='approved_manual_prep', approved_by='user', approved_at=? WHERE id=?", (db.utc_now(), kit_id))
        return kit_id

    def clone_publishable_kit(self, base_kit_id: str, *, campaign_slug: str = "yourrage") -> str:
        base = db.one("SELECT * FROM render_kits WHERE id = ?", (base_kit_id,))
        self.assertIsNotNone(base)
        suffix = db.new_id("pubclone")
        kit_dir = Path(self._tmp.name) / "render_kits" / f"publish-clone-{campaign_slug}-{suffix}"
        kit_dir.mkdir(parents=True, exist_ok=True)
        copied = {}
        for field in ("review_video_path", "caption_path", "transcript_path", "checklist_path", "source_path", "risk_path"):
            source = Path(str(base[field]))
            target = kit_dir / source.name
            shutil.copy2(source, target)
            copied[field] = target
        kit_id = db.create_render_kit(
            str(base["nomination_id"]),
            f"{campaign_slug} publish ready {suffix}",
            copied["review_video_path"],
            copied["caption_path"],
            copied["transcript_path"],
            copied["checklist_path"],
            copied["source_path"],
            copied["risk_path"],
            is_demo=False,
            campaign_slug=campaign_slug,
        )
        db.execute(
            "UPDATE render_kits SET review_status='approved_manual_prep', approved_by='user', approved_at=? WHERE id=?",
            (db.utc_now(), kit_id),
        )
        return kit_id

    def test_publish_dry_run_prepares_and_validates_approved_kit(self):
        kit_id = self.make_publishable_kit()
        package = publishing.create_publish_package(kit_id, platforms=["tiktok", "instagram", "youtube"])
        self.assertEqual(package["status"], "ready")
        self.assertEqual(package["platforms"], ["tiktok", "instagram", "youtube"])
        self.assertIn("#yourrage", package["hashtags"])
        job = publishing.create_publish_job({"package_id": package["id"], "mode": "dry_run", "platforms": ["tiktok", "youtube"]})
        result = publishing.execute_publish_job(job["id"])
        self.assertEqual(result["status"], "succeeded")
        updated = publishing.get_publish_job(job["id"])
        self.assertEqual(updated["status"], "dry_run_succeeded")
        self.assertEqual(updated["platforms"], ["tiktok", "youtube"])
        self.assertIn("Apikey <redacted>", json.dumps(updated["provider_response"]))

    def test_approval_auto_slot_creates_deferred_dry_run_publish_job(self):
        now = datetime(2026, 6, 14, 17, 15, tzinfo=timezone.utc)
        kit_id = self.make_publishable_kit()

        scheduled = publishing.schedule_approved_kit(kit_id, now=now, requested_by="test")

        self.assertEqual(scheduled["status"], "scheduled")
        self.assertEqual(scheduled["publish_package"]["kit_id"], kit_id)
        self.assertEqual(scheduled["publish_job"]["kit_id"], kit_id)
        self.assertEqual(scheduled["publish_job"]["mode"], "dry_run")
        self.assertEqual(scheduled["publish_job"]["status"], "scheduled")
        self.assertEqual(scheduled["publish_job"]["stage"], "waiting-for-slot")
        scheduled_at = datetime.fromisoformat(scheduled["publish_job"]["scheduled_at"])
        self.assertGreater(scheduled_at, now)
        self.assertEqual(scheduled_at.minute, 14)
        self.assertEqual(db.rows("SELECT * FROM job_runs WHERE intent='publish_dry_run'"), [])

        again = publishing.schedule_approved_kit(kit_id, now=now, requested_by="test")

        self.assertEqual(again["publish_job"]["id"], scheduled["publish_job"]["id"])
        self.assertEqual(len(db.rows("SELECT * FROM publish_jobs WHERE kit_id=?", (kit_id,))), 1)

    def test_publish_slot_allocator_fills_backlog_on_future_14_minute_slots(self):
        now = datetime(2026, 6, 14, 17, 15, tzinfo=timezone.utc)
        base_kit_id = self.make_publishable_kit()
        kit_ids = [base_kit_id] + [self.clone_publishable_kit(base_kit_id) for _ in range(47)]

        for kit_id in kit_ids:
            publishing.schedule_approved_kit(kit_id, now=now, requested_by="test")
        slots = [
            str(row["scheduled_at"])
            for row in db.rows("SELECT scheduled_at FROM publish_jobs WHERE status='scheduled' ORDER BY scheduled_at ASC")
        ]
        parsed = [datetime.fromisoformat(value) for value in slots]

        self.assertEqual(len(set(slots)), 48)
        self.assertEqual(parsed, sorted(parsed))
        self.assertTrue(all(value > now for value in parsed))
        self.assertTrue(all(value.minute == 14 for value in parsed))
        self.assertTrue(all((right - left) == timedelta(hours=3) for left, right in zip(parsed, parsed[1:])))

    def test_publish_slot_rebalance_avoids_adjacent_streamers_when_possible(self):
        now = datetime(2026, 6, 14, 17, 15, tzinfo=timezone.utc)
        base_kit_id = self.make_publishable_kit()
        kit_ids = [
            self.clone_publishable_kit(base_kit_id, campaign_slug=slug)
            for slug in ["yourrage", "yourrage", "yourrage", "plaqueboymax", "plaqueboymax", "jasontheween"]
        ]

        for kit_id in kit_ids:
            publishing.schedule_approved_kit(kit_id, now=now, requested_by="test")

        rows = db.rows(
            """
            SELECT r.campaign_slug, p.scheduled_at
            FROM publish_jobs p
            JOIN render_kits r ON r.id = p.kit_id
            WHERE p.status='scheduled'
            ORDER BY p.scheduled_at ASC
            """
        )
        slugs = [str(row["campaign_slug"]) for row in rows]
        self.assertEqual(len(slugs), 6)
        self.assertTrue(all(left != right for left, right in zip(slugs, slugs[1:])), slugs)

    def test_publish_schedule_tick_queues_due_dry_run_once(self):
        now = datetime(2026, 6, 14, 17, 15, tzinfo=timezone.utc)
        kit_id = self.make_publishable_kit()
        scheduled = publishing.schedule_approved_kit(kit_id, now=now, requested_by="test")
        due_at = datetime.fromisoformat(scheduled["publish_job"]["scheduled_at"])

        early = publishing.publish_schedule_tick(now=due_at - timedelta(minutes=1))

        self.assertEqual(early["queued"], [])
        self.assertEqual(db.rows("SELECT * FROM job_runs WHERE intent='publish_dry_run'"), [])

        due = publishing.publish_schedule_tick(now=due_at)

        self.assertEqual(due["status"], "queued")
        self.assertEqual(len(due["queued"]), 1)
        self.assertEqual(due["queued"][0]["intent"], "publish_dry_run")
        queued_job = publishing.get_publish_job(scheduled["publish_job"]["id"])
        self.assertEqual(queued_job["status"], "queued")
        self.assertEqual(queued_job["stage"], "queued-for-hermes")
        self.assertEqual(queued_job["hermes_job_id"], due["queued"][0]["id"])

        repeated = publishing.publish_schedule_tick(now=due_at + timedelta(minutes=1))

        self.assertEqual(repeated["queued"], [])
        self.assertEqual(len(db.rows("SELECT * FROM job_runs WHERE intent='publish_dry_run'")), 1)

    def test_publish_schedule_tick_backfills_approved_unslotted_kits(self):
        now = datetime(2026, 6, 14, 17, 15, tzinfo=timezone.utc)
        base_kit_id = self.make_publishable_kit()
        second_kit_id = self.clone_publishable_kit(base_kit_id, campaign_slug="plaqueboymax")

        tick = publishing.publish_schedule_tick(now=now)

        self.assertEqual(tick["queued"], [])
        self.assertEqual([item["kit_id"] for item in tick["scheduled_backlog"]], [base_kit_id, second_kit_id])
        self.assertEqual(len({item["scheduled_at"] for item in tick["scheduled_backlog"]}), 2)
        jobs = db.rows("SELECT * FROM publish_jobs ORDER BY scheduled_at ASC")
        self.assertEqual(len(jobs), 2)
        self.assertEqual([row["kit_id"] for row in jobs], [base_kit_id, second_kit_id])
        self.assertTrue(all(str(row["status"]) == "scheduled" for row in jobs))
        self.assertTrue(all(datetime.fromisoformat(str(row["scheduled_at"])).minute == 14 for row in jobs))

    def test_reschedule_approved_backlog_moves_stale_jobs_to_future_slots(self):
        old_now = datetime(2026, 6, 14, 17, 15, tzinfo=timezone.utc)
        new_now = datetime(2026, 6, 18, 15, 30, tzinfo=timezone.utc)
        base_kit_id = self.make_publishable_kit()
        kit_ids = [
            base_kit_id,
            self.clone_publishable_kit(base_kit_id, campaign_slug="plaqueboymax"),
            self.clone_publishable_kit(base_kit_id, campaign_slug="jasontheween"),
        ]

        for kit_id in kit_ids:
            publishing.schedule_approved_kit(kit_id, now=old_now, requested_by="test")
        stale_jobs = db.rows("SELECT * FROM publish_jobs ORDER BY scheduled_at ASC")
        self.assertTrue(any(datetime.fromisoformat(str(row["scheduled_at"])) < new_now for row in stale_jobs))

        result = publishing.reschedule_approved_backlog(now=new_now, requested_by="test")

        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["rescheduled_count"], 3)
        slots = [datetime.fromisoformat(str(item["scheduled_at"])) for item in result["jobs"]]
        self.assertEqual(len(set(slots)), 3)
        self.assertTrue(all(slot > new_now for slot in slots))
        self.assertTrue(all(slot.minute == 14 for slot in slots))
        self.assertEqual([row["review_status"] for row in db.rows("SELECT review_status FROM render_kits ORDER BY id ASC")], ["approved_manual_prep"] * 3)

    def test_reschedule_approved_backlog_normalizes_legacy_default_platforms_to_tiktok(self):
        kit_id = self.make_publishable_kit()
        old_slot = datetime(2026, 6, 14, 17, 14, tzinfo=timezone.utc).isoformat(timespec="seconds")
        package = publishing.create_publish_package(kit_id, platforms=["tiktok", "instagram", "youtube"])
        job = publishing.create_publish_job(
            {
                "package_id": package["id"],
                "mode": "dry_run",
                "platforms": ["tiktok", "instagram", "youtube"],
                "scheduled_at": old_slot,
                "defer_hermes_until_due": True,
            }
        )
        self.assertEqual(job["platforms"], ["tiktok", "instagram", "youtube"])

        publishing.reschedule_approved_backlog(now=datetime(2026, 6, 18, 15, 30, tzinfo=timezone.utc), requested_by="test")

        self.assertEqual(publishing.get_publish_job(job["id"])["platforms"], ["tiktok"])
        self.assertEqual(publishing.get_publish_package(package["id"])["platforms"], ["tiktok"])

    def test_publish_blocks_unapproved_demo_and_invalid_platforms(self):
        unapproved_id = self.make_publishable_kit(approved=False)
        with self.assertRaises(publishing.PublishError) as unapproved:
            publishing.create_publish_package(unapproved_id)
        self.assertIn("approved", unapproved.exception.detail.lower())

        demo_id = self.make_publishable_kit(approved=True, is_demo=True)
        with self.assertRaises(publishing.PublishError) as demo:
            publishing.create_publish_package(demo_id)
        self.assertIn("demo", demo.exception.detail.lower())

        approved_id = self.make_publishable_kit(approved=True)
        with self.assertRaises(publishing.PublishError):
            publishing.create_publish_package(approved_id, platforms=["tiktok", "myspace"])

    def test_live_publish_requires_key_warmup_and_confirmation(self):
        kit_id = self.make_publishable_kit()
        package = publishing.create_publish_package(kit_id)
        job = publishing.create_publish_job({"package_id": package["id"], "mode": "live", "platforms": ["tiktok"]})
        self.assertEqual(job["status"], "awaiting_confirmation")
        with self.assertRaises(publishing.PublishError) as blocked:
            publishing.confirm_live_publish(job["id"])
        self.assertIn("Upload-Post API key missing", blocked.exception.detail)

        result = publishing.execute_publish_job(job["id"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("Final live-post confirmation is missing", result["blocker"])

    def test_publish_readiness_is_yellow_until_uploadpost_key_and_warmup(self):
        status = publishing.publish_status()
        self.assertEqual(status["status"], "yellow")
        self.assertFalse(status["provider"]["live_ready"])
        readiness = db.readiness_report()
        autopost = next(item for item in readiness["features"] if item["name"] == "Autopost readiness")
        self.assertEqual(autopost["status"], "yellow")

    def test_uploadpost_readiness_is_platform_specific(self):
        kit_id = self.make_publishable_kit()
        with mock.patch.dict(os.environ, {"UPLOAD_POST_API_KEY": "secret_test_key"}, clear=False):
            status = publishing.set_publish_settings(
                {
                    "mode": "live",
                    "platform_warmup": {
                        "tiktok": True,
                        "instagram": False,
                        "youtube": False,
                        "facebook": False,
                    },
                }
            )
            self.assertEqual(status["default_platforms"], ["tiktok"])
            self.assertTrue(status["provider"]["platforms"]["tiktok"]["live_ready"])
            self.assertFalse(status["provider"]["platforms"]["instagram"]["warmup_complete"])
            self.assertFalse(status["provider"]["platforms"]["youtube"]["warmup_complete"])
            self.assertFalse(status["provider"]["platforms"]["facebook"]["warmup_complete"])

            package = publishing.create_publish_package(kit_id)
            self.assertEqual(package["platforms"], ["tiktok"])
            instagram_package = publishing.create_publish_package(kit_id, platforms=["instagram"])
            instagram_job = publishing.create_publish_job({"package_id": instagram_package["id"], "mode": "live", "platforms": ["instagram"]})
            with self.assertRaises(publishing.PublishError) as blocked:
                publishing.confirm_live_publish(instagram_job["id"])
            self.assertIn("Instagram account warm-up is not marked complete", blocked.exception.detail)

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
        self.assertAlmostEqual(caption_start_for_group(0.04, 0.39, "I SHOULD"), 0.04, places=3)

    def test_editorial_gate_uses_freshness_window_view_floor(self):
        stale_clip = {
            "id": "clip_stale_floor",
            "campaign_slug": "yourrage",
            "title": "Fresh streamer moment",
            "duration": 24.0,
            "view_count": 121,
            "risk_flags_json": json.dumps(["campaign_project_yourrage", "source_media_verified_local"]),
        }
        fresh_clip = {
            **stale_clip,
            "id": "clip_top_24h_floor",
            "risk_flags_json": json.dumps(
                [
                    "campaign_project_yourrage",
                    "source_media_verified_local",
                    "editorial_indexed_top_fresh",
                    "fresh_window_24h",
                    "top_24h_candidate",
                ]
            ),
        }

        stale_gate = db.editorial_candidate_gate(stale_clip, "yourrage")
        fresh_gate = db.editorial_candidate_gate(fresh_clip, "yourrage")

        self.assertEqual(stale_gate["thresholds"]["min_views"], 1350)
        self.assertIn("editorial floor", "; ".join(stale_gate["blockers"]))
        self.assertEqual(fresh_gate["thresholds"]["min_views"], 5)
        self.assertEqual(fresh_gate["status"], "green")
        delayed_start, delayed_end = apply_caption_audio_sync_delay(1.55, 2.11)
        self.assertEqual(CAPTION_AUDIO_SYNC_DELAY_SECONDS, 0.0)
        self.assertAlmostEqual(delayed_start, 1.55, places=3)
        self.assertAlmostEqual(delayed_end, 2.11, places=3)

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

    def test_editorial_gate_decreases_view_floor_through_three_day_window(self):
        clip = {
            "id": "clip_three_day_floor",
            "campaign_slug": "jasontheween",
            "title": "Jason had the lobby yelling",
            "duration": 31.0,
            "view_count": 34,
            "risk_flags_json": json.dumps(["campaign_project_jasontheween", "source_media_verified_local", "fresh_window_72h"]),
        }

        below_floor = db.editorial_candidate_gate(clip, "jasontheween")
        at_floor = db.editorial_candidate_gate({**clip, "view_count": 35}, "jasontheween")

        self.assertEqual(below_floor["thresholds"]["min_views"], 35)
        self.assertNotEqual(below_floor["status"], "green")
        self.assertEqual(at_floor["status"], "green")

    def test_ensemble_caption_beats_do_not_apply_second_render_delay(self):
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
        self.assertAlmostEqual(beats[0]["start"], 1.0, places=3)
        self.assertAlmostEqual(beats[0]["audio_sync_delay_seconds"], 0.0, places=3)

    def test_word_timed_caption_beats_start_on_spoken_word(self):
        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_sync_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_sync_test"] = module
        spec.loader.exec_module(module)

        beats = module.caption_beats_from_transcript(
            {
                "provider": "forced_alignment_test",
                "word_timings_json": json.dumps(
                    [
                        {"word": "No", "start": 1.0, "end": 1.12},
                        {"word": "shit", "start": 1.16, "end": 1.31},
                        {"word": "gang", "start": 1.8, "end": 1.98},
                    ]
                ),
            }
        )

        self.assertEqual(beats[0]["text"], "NO SHIT")
        self.assertAlmostEqual(beats[0]["source_start"], 1.0, places=3)
        self.assertLessEqual(beats[0]["start"] - beats[0]["source_start"], 0.05)
        self.assertAlmostEqual(beats[0]["audio_sync_delay_seconds"], 0.0, places=3)

    def test_fast_ensemble_captions_trim_previous_tail_instead_of_lagging_next_word(self):
        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_fast_sync_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_fast_sync_test"] = module
        spec.loader.exec_module(module)

        beats = module.caption_beats_from_transcript(
            {
                "provider": "ensemble_timestamp_consensus_v1",
                "segments_json": json.dumps(
                    [
                        {
                            "caption_beat": True,
                            "text": "I'M NOT",
                            "start": 0.59,
                            "end": 1.12,
                            "source_start": 0.59,
                            "source_end": 0.96,
                            "timing_mode": "ensemble_consensus",
                            "model_votes": 4,
                            "vote_spread_seconds": 0.08,
                        },
                        {
                            "caption_beat": True,
                            "text": "GONNA LIE",
                            "start": 0.96,
                            "end": 1.35,
                            "source_start": 0.96,
                            "source_end": 1.19,
                            "timing_mode": "ensemble_consensus",
                            "model_votes": 4,
                            "vote_spread_seconds": 0.08,
                        },
                    ]
                ),
            }
        )

        self.assertEqual([beat["text"] for beat in beats], ["I'M NOT", "GONNA LIE"])
        self.assertLessEqual(beats[1]["start"] - beats[1]["source_start"], 0.08)
        self.assertLessEqual(beats[0]["end"], beats[1]["start"] - module.CAPTION_BEAT_GAP + 0.001)

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
        from script.audit_top_card_reference import compare_visual_similarity, masked_card_similarity, measure_overlay, measure_reference

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
            overlay = Image.open(path).convert("RGBA")
            metrics = measure_overlay(overlay)
            self.assertGreaterEqual(metrics["card_width"], 879)
            self.assertLessEqual(metrics["card_width"], 883)
            self.assertGreaterEqual(metrics["card_height"], 156)
            self.assertLessEqual(metrics["card_height"], 158)
            self.assertGreaterEqual(metrics["text_height"], 120)
            self.assertLessEqual(metrics["text_height"], 126)
            self.assertGreaterEqual(metrics["left_pad"], 33)
            self.assertLessEqual(metrics["left_pad"], 38)
            self.assertGreaterEqual(metrics["right_pad"], 30)
            self.assertLessEqual(metrics["right_pad"], 34)
            self.assertGreaterEqual(metrics["top_pad"], 21)
            self.assertLessEqual(metrics["top_pad"], 22)
            self.assertGreaterEqual(metrics["bottom_pad"], 10)
            self.assertLessEqual(metrics["bottom_pad"], 14)
            self.assertLess(abs(metrics["card_center_x"] - 540), 2)

    def test_short_two_line_top_hook_hugs_visible_text_with_reference_padding(self):
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
            self.assertFalse(any(module.is_emoji_char(char) for char in hook))
            metrics = measure_overlay(Image.open(path).convert("RGBA"))
            self.assertGreaterEqual(metrics["card_width"], 500)
            self.assertLessEqual(metrics["card_width"], 545)
            self.assertGreaterEqual(metrics["left_pad"], 33)
            self.assertLessEqual(metrics["left_pad"], 36)
            self.assertLess(abs(metrics["card_center_x"] - 540), 4)

    def test_long_top_hook_fits_inside_reference_card(self):
        from PIL import Image
        from script.audit_top_card_reference import measure_overlay

        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_long_top_card_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_long_top_card_test"] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "title_card.png"
            hook = module.headline_card(
                path,
                "Diana Lim Hits An Insane Combo On Sabrina Alvarez At JasonTheWeen's Boxing Event",
                "jasontheween",
            )
            self.assertIn("Diana Lim", hook)
            metrics = measure_overlay(Image.open(path).convert("RGBA"))
            self.assertLessEqual(metrics["card_width"], 883)
            self.assertGreaterEqual(metrics["left_pad"], 30)
            self.assertGreaterEqual(metrics["right_pad"], 30)
            self.assertLess(abs(metrics["card_center_x"] - 540), 4)

    def test_each_top_hook_line_is_centered_within_card(self):
        from PIL import Image
        from script.audit_top_card_reference import measure_overlay

        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_top_card_center_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_top_card_center_test"] = module
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "title_card.png"
            hook = module.headline_card(path, "YourRAGE got asked an awkward friendship question", "yourrage")
            self.assertIn("friendship question", hook)
            metrics = measure_overlay(Image.open(path).convert("RGBA"))
            self.assertEqual(metrics["line_count"], 2)
            deltas = [abs(item["center_delta"]) for item in metrics["line_metrics"]]
            self.assertLessEqual(max(deltas), 12, metrics["line_metrics"])

    def test_top_hook_does_not_append_fake_stream_suffix(self):
        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_suffix_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_suffix_test"] = module
        spec.loader.exec_module(module)

        hook = module.reference_top_hook_text("Max got Lucki talking about turning thirty")
        self.assertEqual(hook, "Max got Lucki talking about turning thirty 🎙️")
        self.assertNotIn("on stream", hook.lower())

    def test_top_hook_uses_contextual_emoji_suffixes(self):
        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_context_emoji_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_context_emoji_test"] = module
        spec.loader.exec_module(module)

        self.assertEqual(module.reference_top_hook_text("Jason sent AsianJeff flying out of the ring"), "Jason sent AsianJeff flying out of the ring 🥊")
        self.assertEqual(module.reference_top_hook_text("YourRAGE found a wild brain training take"), "YourRAGE found a wild brain training take 🧠")
        self.assertEqual(module.reference_top_hook_text("Max broke down the raw vocals and adlibs live"), "Max broke down the raw vocals and adlibs live 🎙️")
        self.assertEqual(module.reference_top_hook_text("YourRAGE debated what Emily should bring to the cookout"), "YourRAGE debated what Emily should bring to the cookout 👀")
        suffixes = {
            module.reference_top_hook_text("Jason sent AsianJeff flying out of the ring").split()[-1],
            module.reference_top_hook_text("YourRAGE found a wild brain training take").split()[-1],
            module.reference_top_hook_text("Max broke down the raw vocals and adlibs live").split()[-1],
            module.reference_top_hook_text("YourRAGE debated what Emily should bring to the cookout").split()[-1],
        }
        self.assertGreaterEqual(len(suffixes), 4)
        self.assertNotIn("🤣🤣", suffixes)

    def test_top_hook_balances_short_two_line_cards(self):
        from PIL import Image, ImageDraw

        module_path = Path(__file__).resolve().parents[1] / "script" / "build_evidence_review_kit.py"
        spec = importlib.util.spec_from_file_location("build_evidence_review_kit_for_line_balance_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["build_evidence_review_kit_for_line_balance_test"] = module
        spec.loader.exec_module(module)

        draw = ImageDraw.Draw(Image.new("RGBA", (720, 1280), (0, 0, 0, 0)), "RGBA")
        style_font = module.top_hook_card_font(34)
        emoji_font = module.top_hook_emoji_font(40)
        lines = module._reference_top_hook_lines(
            draw,
            "Max got Lucki talking about turning thirty 🤣🤣",
            style_font,
            emoji_font,
            548,
        )
        widths = [module.mixed_text_size(draw, line, style_font, emoji_font)[0] for line in lines]
        self.assertEqual(lines, ["Max got Lucki talking", "about turning thirty 🤣🤣"])
        self.assertGreaterEqual(min(widths) / max(widths), 0.80)

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

    def test_manual_editorial_review_pick_warns_on_view_floor_without_bypassing_other_blockers(self):
        manual_pick = {
            "id": "clip_manual_pick",
            "campaign_slug": "plaqueboymax",
            "title": "strong manual pick",
            "duration": 35,
            "view_count": 1200,
            "risk_flags": ["campaign_project_plaqueboymax", "manual_editorial_review_pick"],
        }
        overlong_pick = {
            **manual_pick,
            "id": "clip_manual_pick_long",
            "duration": 59.9,
        }

        manual_gate = db.editorial_candidate_gate(manual_pick, "plaqueboymax")
        overlong_gate = db.editorial_candidate_gate(overlong_pick, "plaqueboymax")

        self.assertEqual(manual_gate["status"], "green")
        self.assertTrue(any("manual editorial review pick" in item for item in manual_gate["warnings"]))
        self.assertNotEqual(overlong_gate["status"], "green")
        self.assertTrue(any("cut must be tighter" in item for item in overlong_gate["blockers"]))

    def test_quota_recovery_pick_relaxes_view_floor_and_weak_title_only(self):
        quota_pick = {
            "id": "clip_quota_recovery_floor",
            "campaign_slug": "yourrage",
            "title": ".",
            "duration": 30.0,
            "view_count": 800,
            "risk_flags_json": json.dumps(["campaign_project_yourrage", "source_media_verified_local"]),
        }
        normal_gate = db.editorial_candidate_gate(quota_pick, "yourrage")
        recovery_gate = db.editorial_candidate_gate(quota_pick, "yourrage", quota_recovery=True)

        self.assertNotEqual(normal_gate["status"], "green")
        self.assertEqual(recovery_gate["status"], "green")
        self.assertTrue(any("quota recovery" in item for item in recovery_gate["warnings"]))
        self.assertFalse(recovery_gate["blockers"])

        metadata_only = {
            **quota_pick,
            "id": "clip_quota_recovery_metadata_only",
            "risk_flags_json": json.dumps(["campaign_project_yourrage", "metadata_only_no_download"]),
        }
        overlong = {**quota_pick, "id": "clip_quota_recovery_overlong", "duration": 59.9}

        self.assertNotEqual(db.editorial_candidate_gate(metadata_only, "yourrage", quota_recovery=True)["status"], "green")
        self.assertNotEqual(db.editorial_candidate_gate(overlong, "yourrage", quota_recovery=True)["status"], "green")

    def test_quote_like_viewer_hooks_stay_clip_specific(self):
        from script import build_evidence_review_kit as module

        rage_hook = module.viewer_hook(
            "YourRAGE: WHAT IS THIS LAND BRO DON'T DON'T DON'T PMO",
            "yourrage",
            "WHAT IS THIS LAND BRO DON'T DON'T DON'T PMO",
        )
        jason_hook = module.viewer_hook(
            "JasonTheWeen: I'M NOT GOING BACK TO ARLINGTON I'M GOING TO PLAY LEAGUE OF LEGENDS AND I'M GAY OKAY",
            "jasontheween",
            "I'M NOT GOING BACK TO ARLINGTON I'M GOING TO PLAY LEAGUE OF LEGENDS AND I'M GAY OKAY",
        )

        self.assertNotIn("had the whole chat watching", rage_hook.lower())
        self.assertNotIn("had the whole chat watching", jason_hook.lower())
        self.assertNotIn("YourRAGE said:", rage_hook)
        self.assertNotIn("Jason said:", jason_hook)
        self.assertEqual(rage_hook, "YourRAGE opened a link and instantly regretted it")
        self.assertEqual(jason_hook, "Jason made a wild Arlington exit plan")

    def test_short_viewer_hooks_gain_context_instead_of_generic_chat_fallback(self):
        from script import build_evidence_review_kit as module

        hook = module.viewer_hook(
            "That is not ExtraEmily",
            "jasontheween",
            "That is not ExtraEmily bear.",
        )

        self.assertNotIn("had the whole chat watching", hook.lower())
        self.assertEqual(hook, "Jason shut down the ExtraEmily comparison")

    def test_active_needs_review_hook_overrides_replace_bad_raw_titles(self):
        from script import build_evidence_review_kit as module

        examples = {
            "clip_e96ab8000070": ("woj the hero", "jasontheween", "Jason got confused by the little book"),
            "clip_b071c40cabbf": ("Nor ro too 😭✌️", "yourrage", "YourRAGE lost it over a wild anime clip"),
            "clip_c314daceaba2": ("Uno Reverse Card", "yourrage", "YourRAGE tried to dodge the Agent and Emily setup"),
            "clip_497dd35b719c": (".", "jasontheween", "Jason's exploration segment went off the rails"),
        }
        for clip_id, (title, handle, expected) in examples.items():
            hook = module.viewer_hook(title, handle, transcript_text="", clip_id=clip_id)
            self.assertEqual(hook, expected)
            self.assertNotIn(" said:", hook)

    def test_hook_quality_selects_good_card_and_blocks_generic_cards(self):
        from clipping_ops_backend import hook_quality

        selected = hook_quality.select_hook_candidate(
            [
                {"text": "YourRAGE had the whole chat watching", "source": "local_fallback"},
                {"text": "YourRAGE said: WHAT IS THIS LAND BRO", "source": "quote_dump"},
                {"text": "Nor ro too 😭✌️", "source": "raw_title"},
                {"text": "YourRAGE opened a link and instantly regretted it", "source": "hermes"},
            ],
            clip_title="Nor ro too 😭✌️",
            handle="yourrage",
            campaign_slug="yourrage",
            transcript_text="WHAT IS THIS LAND BRO DON'T DON'T DON'T PMO",
            recent_hooks=[],
        )

        self.assertEqual(selected["status"], "succeeded")
        self.assertEqual(selected["selected_hook"], "YourRAGE opened a link and instantly regretted it")
        self.assertEqual(selected["selected_source"], "hermes")
        self.assertTrue(any("generic_chat_hook" in item["violations"] for item in selected["candidates"]))
        self.assertTrue(any("quote_dump_hook" in item["violations"] for item in selected["candidates"]))
        self.assertTrue(any("raw_title_echo" in item["violations"] for item in selected["candidates"]))

        blocked = hook_quality.select_hook_candidate(
            [
                {"text": "YourRAGE had the whole chat watching", "source": "local_fallback"},
                {"text": "YourRAGE said: WHAT IS THIS LAND BRO", "source": "quote_dump"},
            ],
            clip_title="Nor ro too 😭✌️",
            handle="yourrage",
            campaign_slug="yourrage",
            transcript_text="WHAT IS THIS LAND BRO DON'T DON'T DON'T PMO",
        )

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["blocker_code"], "blocked_hook_quality")
        self.assertIn("No hook candidate passed", blocked["blocker"])

    def test_hook_quality_blocks_raw_asr_and_repetition_cards(self):
        from clipping_ops_backend import hook_quality

        raw_loop = hook_quality.hook_quality_violations(
            "YourRAGE WHO ELSE WE BRINGING ELSE WE BRINGING EMILY EMILY GOT A SLIDE",
            clip_title="YourRAGE: WHO ELSE WE BRINGING ELSE WE BRINGING EMILY EMILY GOT A SLIDE",
            handle="yourrage",
            transcript_text="WHO ELSE WE BRINGING ELSE WE BRINGING EMILY EMILY GOT A SLIDE",
        )
        quote_dump = hook_quality.hook_quality_violations(
            "Jason said: Yeah, I got a shotgun",
            clip_title="JasonTheWeen: Yeah, I got a shotgun.",
            handle="jasontheween",
            transcript_text="Yeah, I got a shotgun.",
        )
        generic = hook_quality.hook_quality_violations("Jason had chat locked in over this moment")
        garbled = hook_quality.hook_quality_violations("BruceDropEmOff tries to get at your ridge for little sisin yonna")
        grounded = hook_quality.hook_quality_violations(
            "YourRAGE debated what Emily should bring to the cookout",
            clip_title="YourRAGE: WHO ELSE WE BRINGING EMILY GOT A SLIDE WHAT'S EMILY'S ITEM TO BRING",
            handle="yourrage",
            transcript_text="WHO ELSE WE BRINGING EMILY GOT A SLIDE WHAT'S EMILY'S ITEM TO BRING",
        )

        self.assertIn("raw_asr_fragment_hook", raw_loop)
        self.assertIn("repetitive_hook", raw_loop)
        self.assertIn("quote_dump_hook", quote_dump)
        self.assertIn("generic_chat_hook", generic)
        self.assertIn("asr_garble_hook", garbled)
        self.assertEqual(grounded, [])

    def test_viewer_hook_rewrites_current_backlog_raw_cards(self):
        from script import build_evidence_review_kit as module

        examples = {
            "clip_c10a586d14f2": (
                "YourRAGE: WHO ELSE WE BRINGING ELSE WE BRINGING EMILY EMILY GOT A SLIDE WHAT'S EMILY'S ITEM TO BRING",
                "yourrage",
                "WHO ELSE WE BRINGING ELSE WE BRINGING EMILY EMILY GOT A SLIDE WHAT'S EMILY'S ITEM TO BRING",
                "YourRAGE debated what Emily should bring to the cookout",
            ),
            "clip_a2c2f13e8daf": (
                "PlaqueBoyMax: YOU FIND THAT IN HER NOTES TAB SHE SAYS SHE WANTS TO BUY HER COUSIN",
                "plaqueboymax",
                "SO YOU FIND THAT IN HER NOTES TAB SHE SAYS SHE WANTS TO BUY HER COUSIN",
                "Max found a notes-tab reveal that got too personal",
            ),
            "clip_262b5c15bf57": (
                "JasonTheWeen: Yeah, I got a shotgun.",
                "jasontheween",
                "Yeah, I got a shotgun.",
                "Jason turned a shotgun comment into a tense room moment",
            ),
            "clip_1ccf25d28b50": (
                "JasonTheWeen: THIS GUY WANTS TO GO MALPHITE MALPHITE TEMPLE HOLY CRINGE MY GOD",
                "jasontheween",
                "THIS GUY WANTS TO GO MALPHITE MALPHITE TEMPLE HOLY CRINGE MY GOD",
                "Jason watched the Malphite pick turn painfully cringe",
            ),
            "clip_e355fd339fa8": (
                "bye",
                "jasontheween",
                "Here I go. Excuse me. Jason! Put your hand out!",
                "Jason got caught in a chaotic crowd moment",
            ),
            "clip_df2df8d8d10f": (
                "bro getting baited 2 mins into stream",
                "jasontheween",
                "I'm not bloated, chill, bro. I did not gain 50 pounds. Ashley, stop.",
                "Jason got baited by chat about gaining weight",
            ),
            "clip_00a2e7760185": (
                "Jason beats his Opponent AsianJeff out of the Ring",
                "jasontheween",
                "There we go, there we go in the ring.",
                "Jason sent AsianJeff flying out of the ring",
            ),
            "clip_b43227e3b961": (
                "BruceDropEmOff tries to get at your ridge for little sisin yonna to sleep w her",
                "plaqueboymax",
                "look sis your way to some pussy bro",
                "Max heard Bruce call out the little-sis pickup bit",
            ),
            "clip_d3bc0093334d": (
                "Emily uses the memory palace",
                "yourrage",
                "Use something called the loci method or a memory palace.",
                "YourRAGE found a wild brain training take",
            ),
            "clip_4a7f9071006e": (
                "response dos",
                "yourrage",
                "I answer no phone call and no DM. Stop telling Max and Silky hit me about no game.",
                "YourRAGE shut down the Paris game pressure",
            ),
            "clip_3e5b975326a7": (
                "Rage thought Emily was going to Florida with Cinna",
                "yourrage",
                "Emily going to Florida with Cinna? Chat keeps trying to make this weird.",
                "YourRAGE reacted to the Emily and Cinna travel rumor",
            ),
        }

        for clip_id, (title, handle, transcript, expected) in examples.items():
            hook = module.viewer_hook(title, handle, transcript_text=transcript, clip_id=clip_id)
            self.assertEqual(hook, expected)
            self.assertNotIn(" said:", hook)

        title = module.campaign_kit_title(
            {"title": "YourRAGE: WHO ELSE WE BRINGING ELSE WE BRINGING EMILY"},
            "yourrage",
            {"full_text": "WHO ELSE WE BRINGING ELSE WE BRINGING EMILY"},
            hook_override="YourRAGE debated what Emily should bring to the cookout",
        )
        self.assertEqual(title, "YourRAGE debated what Emily should bring to the cookout")

    def test_campaign_review_hook_quality_blocks_before_rendering(self):
        from clipping_ops_backend.hook_quality import HookQualityError
        from script import build_evidence_review_kit as module

        candidate = module.Candidate(
            clip={
                "id": "clip_bad_hook_quality",
                "campaign_slug": "yourrage",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/yourragegaming/clip/bad-hook-quality",
                "title": ".",
                "duration": 21.0,
                "view_count": 2500,
                "local_media_path": str(Path(self._tmp.name) / "bad-hook.mp4"),
                "provenance": "official_api_metadata",
                "risk_flags": ["campaign_project_yourrage", "source_media_verified_local"],
            },
            route={"creator_handle": "yourrage", "platform": "twitch"},
            rules=[{"campaign_id": "yourrage", "title": "YourRAGE rules"}],
        )
        transcript = {
            "full_text": "ok bro",
            "segments_json": json.dumps([{"start": 0.0, "end": 1.0, "text": "ok bro"}]),
            "word_timings_json": json.dumps(
                [
                    {"start": 0.0, "end": 0.3, "word": "ok"},
                    {"start": 0.3, "end": 0.6, "word": "bro"},
                ]
            ),
        }
        beats = [{"start": 0.0, "end": 0.8, "text": "OK BRO"}]

        with mock.patch.object(module, "pick_candidate", return_value=candidate), \
            mock.patch.object(module, "ensure_local_media", return_value=Path(candidate.clip["local_media_path"])), \
            mock.patch.object(module, "ensure_transcript", return_value=transcript), \
            mock.patch.object(module, "best_caption_beats_for_transcript", return_value=(beats, {"source": "test"})), \
            mock.patch.object(module, "render_review_video") as render:
            with self.assertRaises(HookQualityError) as raised:
                module.build_review_kit(campaign_slug="yourrage", profile=db.CAMPAIGN_SHORT_PROFILE)

        render.assert_not_called()
        payload = raised.exception.payload
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["blocker_code"], "blocked_hook_quality")

    def test_hermes_hook_candidates_can_replace_blocked_local_fallback(self):
        from script import build_evidence_review_kit as module

        hook, payload = module.approve_viewer_hook(
            {
                "id": "clip_hermes_hook_candidate",
                "title": ".",
            },
            "yourrage",
            "ok bro",
            "yourrage",
            hook_candidates=[
                {"text": "YourRAGE said: ok bro", "source": "local_quote_dump"},
                {"text": "YourRAGE opened a link and instantly regretted it", "source": "hermes"},
            ],
        )

        self.assertEqual(hook, "YourRAGE opened a link and instantly regretted it")
        self.assertEqual(payload["selected_source"], "hermes")
        self.assertEqual(payload["candidates"][0]["status"], "blocked")

    def test_campaign_build_records_hook_quality_blocker_from_builder(self):
        from clipping_ops_backend.server import build_campaign_reviews

        media = Path(self._tmp.name) / "source_media" / "hook-blocked.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"source proof")
        db.upsert_clip_candidate(
            {
                "id": "clip_hook_quality_builder_blocked",
                "campaign_slug": "yourrage",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/yourragegaming/clip/hook-quality-builder-blocked",
                "creator_id": "yourragegaming",
                "title": "YourRAGE opened a wild stream link",
                "duration": 22.0,
                "view_count": 12000,
                "clip_created_at": "2026-06-14T12:00:00Z",
                "local_media_path": str(media),
                "provenance": "official_api_metadata",
                "risk_flags": ["campaign_project_yourrage", "source_media_verified_local"],
            }
        )
        db.create_campaign_evidence(
            {
                "campaign_id": "yourrage",
                "evidence_type": "campaign_rules",
                "title": "YourRAGE campaign rules",
                "source_url": "https://clipping.net/dashboard/campaigns/yourrage-x-clipping",
                "extracted_text": "Source route: Twitch handle yourragegaming.",
                "confidence": 0.9,
            }
        )
        blocked_payload = {
            "status": "blocked",
            "blocker_code": "blocked_hook_quality",
            "blocker": "No hook candidate passed the top-card quality gate.",
            "clip_id": "clip_hook_quality_builder_blocked",
        }

        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["python", "script/build_evidence_review_kit.py"],
                0,
                stdout=json.dumps(blocked_payload),
                stderr="",
            ),
        ) as run:
            result = build_campaign_reviews("yourrage", limit=1, style=db.CAMPAIGN_SHORT_PROFILE)

        run.assert_called_once()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("blocked_hook_quality" in blocker for blocker in result["blockers"]))
        job = db.visible_jobs(limit=1)[0]
        self.assertEqual(job["status"], "blocked")
        self.assertIn("blocked_hook_quality", job["error"])

    def test_campaign_build_passes_hermes_hook_candidates_to_builder(self):
        from clipping_ops_backend.server import build_campaign_reviews

        media = Path(self._tmp.name) / "source_media" / "hook-candidates.mp4"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"source proof")
        clip_id = db.upsert_clip_candidate(
            {
                "id": "clip_hook_candidates_passed",
                "campaign_slug": "yourrage",
                "source_platform": "twitch",
                "source_url": "https://www.twitch.tv/yourragegaming/clip/hook-candidates-passed",
                "creator_id": "yourragegaming",
                "title": "YourRAGE opened a wild stream link",
                "duration": 22.0,
                "view_count": 12000,
                "clip_created_at": "2026-06-14T12:00:00Z",
                "local_media_path": str(media),
                "provenance": "official_api_metadata",
                "risk_flags": ["campaign_project_yourrage", "source_media_verified_local"],
            }
        )
        db.create_campaign_evidence(
            {
                "campaign_id": "yourrage",
                "evidence_type": "campaign_rules",
                "title": "YourRAGE campaign rules",
                "source_url": "https://clipping.net/dashboard/campaigns/yourrage-x-clipping",
                "extracted_text": "Source route: Twitch handle yourragegaming.",
                "confidence": 0.9,
            }
        )
        hook_candidates = [{"text": "YourRAGE opened a link and instantly regretted it", "source": "hermes"}]

        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["python", "script/build_evidence_review_kit.py"],
                0,
                stdout=json.dumps({"status": "blocked", "blocker_code": "test_stop", "blocker": "stop after command capture"}),
                stderr="",
            ),
        ) as run:
            build_campaign_reviews(
                "yourrage",
                limit=1,
                style=db.CAMPAIGN_SHORT_PROFILE,
                hook_candidates_by_clip={clip_id: hook_candidates},
            )

        command = run.call_args.args[0]
        self.assertIn("--hook-candidates-json", command)
        raw = command[command.index("--hook-candidates-json") + 1]
        self.assertEqual(json.loads(raw), hook_candidates)

    def test_quota_recovery_orders_recent_low_view_clip_before_old_high_view_clip(self):
        old_high_view = {
            "id": "clip_old_high_view",
            "campaign_slug": "plaqueboymax",
            "title": "Plaque old viral moment",
            "duration": 29.0,
            "view_count": 90000,
            "clip_created_at": "2026-05-01T02:00:00Z",
            "local_media_path": "/tmp/old-high-view.mp4",
            "risk_flags_json": json.dumps(["campaign_project_plaqueboymax", "source_media_verified_local"]),
        }
        recent_low_view = {
            "id": "clip_recent_low_view",
            "campaign_slug": "plaqueboymax",
            "title": "Plaque had stream confused",
            "duration": 28.0,
            "view_count": 6,
            "clip_created_at": "2026-06-11T21:00:00Z",
            "risk_flags_json": json.dumps(
                ["campaign_project_plaqueboymax", "metadata_only_no_download", "fresh_window_24h", "top_24h_candidate"]
            ),
        }

        ordered = db.review_candidate_order([old_high_view, recent_low_view], "plaqueboymax", quota_recovery=True)

        self.assertEqual(ordered[0]["id"], "clip_recent_low_view")
        self.assertEqual(ordered[0]["review_priority"]["freshness_window_hours"], 24)

    def test_quota_recovery_sidecar_keeps_editorial_classifier_green(self):
        kit_id = self.make_publishable_kit(approved=False, is_demo=False)
        kit = db.one("SELECT * FROM render_kits WHERE id=?", (kit_id,))
        nomination = db.one("SELECT * FROM render_nominations WHERE id=?", (kit["nomination_id"],))
        clip_id = json.loads(nomination["clip_candidate_ids_json"])[0]
        db.execute("UPDATE clip_candidates SET view_count=? WHERE id=?", (800, clip_id))
        clip = db.one("SELECT * FROM clip_candidates WHERE id=?", (clip_id,))
        kit_dir = Path(kit["review_video_path"]).parent
        (kit_dir / "render_text_manifest.json").write_text(
            json.dumps(
                {
                    "profile": "campaign_short_final_v1",
                    "rendered_text": {
                        "hook_card": "YourRAGE had chat crying",
                        "caption_beats": ["CHAT LOST", "IT"],
                        "composition": {"mode": "streamer_center_preserve_source"},
                    },
                }
            ),
            encoding="utf-8",
        )
        (kit_dir / "editorial_review.json").write_text(
            json.dumps(
                {
                    "status": "green",
                    "blockers": [],
                    "warnings": ["quota recovery pick below normal view floor"],
                    "thresholds": {"quota_recovery": True},
                }
            ),
            encoding="utf-8",
        )

        proof = db.editorial_review_for_rendered_kit(clip, kit_dir, "yourrage", require_sidecar=True)

        self.assertEqual(proof["status"], "green")
        self.assertFalse(proof["blockers"])

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

    def test_visible_jobs_compact_omits_heavy_json_and_truncates_text(self):
        job_id = db.create_job(
            "heavy job",
            "render",
            "failed",
            "failed",
            50,
            logs="x" * 1000,
            error="y" * 1000,
            payload={"large": "p" * 1000},
            result={"large": "r" * 1000},
        )

        compact = db.visible_jobs(limit=1, compact=True)[0]

        self.assertEqual(compact["id"], job_id)
        self.assertNotIn("payload", compact)
        self.assertNotIn("result", compact)
        self.assertNotIn("payload_json", compact)
        self.assertNotIn("result_json", compact)
        self.assertLessEqual(len(compact["logs"]), 240)
        self.assertLessEqual(len(compact["error"]), 240)

    def test_hermes_job_dedupe_and_cancel(self):
        first = db.create_job_intent("refresh_campaign_project", {"campaign_slug": "kalshi"}, campaign_slug="kalshi")
        second = db.create_job_intent("refresh_campaign_project", {"campaign_slug": "kalshi"}, campaign_slug="kalshi")
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["deduped"])

        cancelled = db.cancel_job(first["id"], actor="test")
        self.assertEqual(cancelled["status"], "cancelled")
        replacement = db.create_job_intent("refresh_campaign_project", {"campaign_slug": "kalshi"}, campaign_slug="kalshi")
        self.assertNotEqual(first["id"], replacement["id"])

    def test_fresh_clip_ladder_prefers_24h_then_expands_only_when_empty(self):
        from clipping_ops_backend import platforms

        now = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)
        calls = []

        def fake_twitch_get(path, params):
            calls.append(params)
            started = str(params["started_at"])
            if started.startswith("2026-06-10"):
                return {"status": "succeeded", "data": {"data": []}, "check_id": "check_24h_empty"}
            return {
                "status": "succeeded",
                "data": {
                    "data": [
                        {
                            "id": "fresh_48h_top",
                            "url": "https://www.twitch.tv/yourragegaming/clip/fresh-48h-top",
                            "title": "Fresh 48h top",
                            "duration": 31,
                            "view_count": 9000,
                            "created_at": "2026-06-09T22:00:00Z",
                        }
                    ]
                },
                "check_id": "check_48h_hit",
            }

        old_get = platforms.twitch_get
        platforms.twitch_get = fake_twitch_get
        try:
            payload = platforms.twitch_fresh_clip_supply_ladder("broadcaster", min_candidates=1, now=now)
        finally:
            platforms.twitch_get = old_get

        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["selected_window_hours"], 48)
        self.assertEqual(payload["data"]["data"][0]["id"], "fresh_48h_top")
        self.assertEqual([item["window_hours"] for item in payload["windows"]], [24, 48])
        self.assertEqual(len(calls), 2)

    def test_review_scheduler_keeps_retrying_until_generated_daily_cap(self):
        now = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)

        def block_queued(result):
            for job in result["queued"]:
                claimed = db.claim_job(job["id"], "hermes-dispatcher", profile=db.hermes_profile())
                db.block_job(
                    claimed["id"],
                    claimed["claim_token"],
                    error="no green candidate",
                    result={"status": "blocked", "created": []},
                )

        result = db.review_schedule_tick(now=now, require_campaign_ready=False)
        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(result["queued"]), 3)
        self.assertTrue(all(item["intent"] == "scheduled_campaign_review_build" for item in result["queued"]))
        self.assertTrue(all(item["payload"]["freshness_ladder_hours"] == [24, 48, 72, 96, 120] for item in result["queued"]))
        block_queued(result)

        for _ in range(7):
            result = db.review_schedule_tick(now=now + timedelta(hours=3), require_campaign_ready=False, force_due=True)
            block_queued(result)
        summary_payload = db.review_schedule_status(now=now + timedelta(hours=21))
        self.assertEqual(summary_payload["attempted_today"], 24)
        self.assertEqual(summary_payload["generated_today"], 0)
        self.assertEqual(summary_payload["daily_cap"], 24)
        self.assertTrue(all(item["attempted_today"] == 8 for item in summary_payload["campaigns"]))
        self.assertTrue(all(item["generated_today"] == 0 for item in summary_payload["campaigns"]))

        retry = db.review_schedule_tick(now=now + timedelta(hours=21), require_campaign_ready=False, force_due=True)
        self.assertEqual(retry["status"], "queued")
        self.assertEqual(len(retry["queued"]), 3)
        self.assertTrue(all(item["payload"]["quota_recovery_mode"] for item in retry["queued"]))

    def test_review_scheduler_caps_after_twenty_four_generated_outputs(self):
        now = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)
        slugs = ["yourrage", "plaqueboymax", "jasontheween"]
        for index in range(24):
            slug = slugs[index % len(slugs)]
            job = db.create_job_intent(
                "scheduled_campaign_review_build",
                {"campaign_slug": slug, "schedule_day": "2026-06-11"},
                campaign_slug=slug,
                requested_by="review-scheduler",
                force_new=True,
            )
            claimed = db.claim_job(job["id"], "hermes-dispatcher", profile=db.hermes_profile())
            db.complete_job(
                claimed["id"],
                claimed["claim_token"],
                result={"status": "succeeded", "created": [{"kit_id": f"kit_created_{index}"}]},
            )

        capped = db.review_schedule_tick(now=now, require_campaign_ready=False, force_due=True)
        self.assertEqual(capped["status"], "capped")
        self.assertEqual(capped["queued"], [])

    def test_review_scheduler_topoff_respects_backlog_limit_when_forced(self):
        now = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)
        for _ in range(23):
            self.make_publishable_kit(approved=False)

        summary_payload = db.review_schedule_status(now=now)
        self.assertEqual(summary_payload["needs_review_backlog"], 23)

        topoff = db.review_schedule_tick(now=now, require_campaign_ready=False, force_due=True)
        self.assertEqual(topoff["status"], "queued")
        self.assertEqual(len(topoff["queued"]), 1)

        blocked = db.review_schedule_tick(now=now + timedelta(minutes=1), require_campaign_ready=False, force_due=True)
        self.assertEqual(blocked["status"], "backlog_blocked")
        self.assertEqual(blocked["queued"], [])

    def test_review_schedule_status_counts_backlog_without_video_validation(self):
        self.make_publishable_kit(approved=False)

        with mock.patch.object(db, "visible_render_kits", side_effect=AssertionError("should not inspect videos")):
            status = db.review_schedule_status()

        self.assertEqual(status["needs_review_backlog"], 1)

    def test_review_schedule_status_excludes_red_sidecar_kits_from_backlog(self):
        kit_id = self.make_publishable_kit(approved=False)
        kit = db.one("SELECT * FROM render_kits WHERE id=?", (kit_id,))
        Path(str(kit["review_video_path"])).parent.joinpath("style_critique.md").write_text(
            "Status: red\nProfile: campaign_short_final_v1\n",
            encoding="utf-8",
        )

        status = db.review_schedule_status()

        self.assertEqual(status["needs_review_backlog"], 0)

    def test_review_scheduler_enters_quota_recovery_after_blocked_attempts(self):
        now = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)
        first = db.review_schedule_tick(now=now, require_campaign_ready=False)
        self.assertEqual(first["status"], "queued")

        claimed = db.claim_job(first["queued"][0]["id"], "hermes-dispatcher", profile=db.hermes_profile())
        db.block_job(
            claimed["id"],
            claimed["claim_token"],
            error="no green candidate",
            result={"status": "blocked", "created": []},
        )

        recovery = db.review_schedule_tick(now=now + timedelta(hours=3), require_campaign_ready=False, force_due=True)
        self.assertEqual(recovery["status"], "queued")
        self.assertTrue(all(item["payload"]["quota_recovery_mode"] for item in recovery["queued"]))
        self.assertTrue(all(item["payload"]["quota_recovery_policy"]["allow_below_view_floor"] for item in recovery["queued"]))
        self.assertTrue(all(item["payload"]["freshness_ladder_hours"][-1] >= 24 * 35 for item in recovery["queued"]))

    def test_review_scheduler_counts_created_kits_not_blocked_attempts(self):
        now = datetime(2026, 6, 11, 6, 0, tzinfo=timezone.utc)
        payload = {"campaign_slug": "yourrage", "schedule_day": "2026-06-11"}
        created_job = db.create_job_intent(
            "scheduled_campaign_review_build",
            payload,
            campaign_slug="yourrage",
            requested_by="review-scheduler",
            force_new=True,
        )
        blocked_job = db.create_job_intent(
            "scheduled_campaign_review_build",
            payload,
            campaign_slug="yourrage",
            requested_by="review-scheduler",
            force_new=True,
        )

        claimed_created = db.claim_job(created_job["id"], "hermes-dispatcher", profile=db.hermes_profile())
        db.complete_job(
            claimed_created["id"],
            claimed_created["claim_token"],
            result={"status": "succeeded", "created": [{"kit_id": "kit_created"}]},
        )
        claimed_blocked = db.claim_job(blocked_job["id"], "hermes-dispatcher", profile=db.hermes_profile())
        db.block_job(
            claimed_blocked["id"],
            claimed_blocked["claim_token"],
            error="no green candidate",
            result={"status": "blocked", "created": []},
        )

        summary_payload = db.review_schedule_status(now=now)
        yourrage = next(item for item in summary_payload["campaigns"] if item["campaign_slug"] == "yourrage")
        self.assertEqual(summary_payload["generated_today"], 1)
        self.assertEqual(yourrage["generated_today"], 1)

    def test_rejecting_review_kit_creates_learning_signal_not_revision_job(self):
        from clipping_ops_backend.server import reject_review_kit

        kit_id = self.make_publishable_kit(approved=False, is_demo=False)
        before_revision_jobs = db.rows("SELECT * FROM job_runs WHERE name='review-kit-revision'")
        result = reject_review_kit(kit_id, "bad clip selection; captions were early", tags=["bad_clip_selection", "caption_timing"])
        self.assertEqual(result["review_status"], "rejected_learning_signal")

        signals = db.review_learning_signals()
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["kit_id"], kit_id)
        self.assertEqual(signals[0]["campaign_slug"], "yourrage")
        self.assertIn("caption_timing", signals[0]["reason_tags"])

        after_revision_jobs = db.rows("SELECT * FROM job_runs WHERE name='review-kit-revision'")
        self.assertEqual(len(after_revision_jobs), len(before_revision_jobs))

    def test_minimax_hermes_status_requires_minimax_profile_provider_and_model(self):
        required_cron_jobs = [
            {"name": name, "profile": "clipping-ops-minimax", "enabled": True}
            for name in db.REQUIRED_CLIPPING_HERMES_CRON_JOBS
        ]
        ready = db.minimax_hermes_status(
            selected_profile="clipping-ops-minimax",
            provider="MiniMax",
            model="MiniMax-M3",
            cron_jobs=required_cron_jobs,
            available=True,
            auth_degraded=False,
        )
        self.assertEqual(ready["status"], "green")

        wrong_provider = db.minimax_hermes_status(
            selected_profile="default",
            provider="OpenAI Codex",
            model="gpt-5.5",
            cron_jobs=required_cron_jobs,
            available=True,
            auth_degraded=False,
        )
        self.assertEqual(wrong_provider["status"], "red")
        self.assertIn("MiniMax", " ".join(wrong_provider["blockers"]))

    def test_minimax_hermes_status_rejects_null_profile_or_missing_scheduler_cron(self):
        null_profile_jobs = [
            {"name": name, "profile": None, "enabled": True}
            for name in db.REQUIRED_CLIPPING_HERMES_CRON_JOBS
        ]
        null_profile = db.minimax_hermes_status(
            selected_profile="clipping-ops-minimax",
            provider="MiniMax",
            model="MiniMax-M3",
            cron_jobs=null_profile_jobs,
            available=True,
            auth_degraded=False,
        )
        self.assertEqual(null_profile["status"], "yellow")
        self.assertIn("must run under clipping-ops-minimax", " ".join(null_profile["blockers"]))

        missing_scheduler = [
            {"name": name, "profile": "clipping-ops-minimax", "enabled": True}
            for name in db.REQUIRED_CLIPPING_HERMES_CRON_JOBS
            if name != "clip-ops scheduler tick"
        ]
        missing = db.minimax_hermes_status(
            selected_profile="clipping-ops-minimax",
            provider="MiniMax",
            model="MiniMax-M3",
            cron_jobs=missing_scheduler,
            available=True,
            auth_degraded=False,
        )
        self.assertEqual(missing["status"], "yellow")
        self.assertIn("clip-ops scheduler tick", " ".join(missing["blockers"]))

        missing_key = db.minimax_hermes_status(
            selected_profile="clipping-ops-minimax",
            provider="MiniMax",
            model="MiniMax-M3",
            cron_jobs=[
                {"name": name, "profile": "clipping-ops-minimax", "enabled": True}
                for name in db.REQUIRED_CLIPPING_HERMES_CRON_JOBS
            ],
            available=True,
            auth_degraded=False,
            api_key_configured=False,
        )
        self.assertEqual(missing_key["status"], "red")
        self.assertIn("API key", " ".join(missing_key["blockers"]))

    def test_scheduler_proof_requires_minimax_profile_scheduled_job(self):
        payload = {
            "campaign_slug": "yourrage",
            "limit": 1,
            "style": db.CAMPAIGN_SHORT_PROFILE,
            "freshness_ladder_hours": list(db.FRESHNESS_LADDER_HOURS),
        }
        db.create_job_intent(
            "scheduled_campaign_review_build",
            payload,
            campaign_slug="yourrage",
            requested_by="review-scheduler",
            hermes_profile_name="default",
            force_new=True,
        )
        wrong_profile = db.scheduled_review_factory_proof_status()
        self.assertFalse(wrong_profile["ready"])
        self.assertEqual(wrong_profile["matching_count"], 0)

        db.create_job_intent(
            "scheduled_campaign_review_build",
            payload,
            campaign_slug="yourrage",
            requested_by="review-scheduler",
            hermes_profile_name="clipping-ops-minimax",
            force_new=True,
        )
        ready = db.scheduled_review_factory_proof_status()
        self.assertTrue(ready["ready"])
        self.assertEqual(ready["matching_count"], 1)

    def test_hermes_caption_alignment_intent_runs_ensemble_retimer(self):
        from script import hermes_job_dispatcher as dispatcher

        with mock.patch(
            "script.hermes_job_dispatcher.run_caption_alignment_command",
            return_value={"status": "succeeded", "command": ["python", "script/ensemble_retime_review_kits.py", "--clip-id", "clip_sync_test"]},
            create=True,
        ) as run:
            result = dispatcher.execute_job(
                {
                    "intent": "retime_review_kit_captions",
                    "payload": {"clip_id": "clip_sync_test", "min_votes": 3},
                    "campaign_slug": "yourrage",
                }
            )

        self.assertEqual(result["status"], "succeeded")
        command = run.return_value["command"]
        self.assertIn("ensemble_retime_review_kits.py", " ".join(command))
        self.assertIn("--clip-id", command)
        self.assertIn("clip_sync_test", command)

    def test_hermes_dispatcher_lock_reports_existing_worker(self):
        from script import hermes_job_dispatcher as dispatcher

        with mock.patch("script.hermes_job_dispatcher.fcntl.flock", side_effect=BlockingIOError):
            with dispatcher.dispatch_lock() as lock_path:
                self.assertIsNone(lock_path)

    def test_ensemble_retimer_uses_same_index_votes_for_short_asr_disagreements(self):
        from script import ensemble_retime_review_kits as retimer

        canonical_targets = [
            {"target_index": 1, "text": "WHAT IS", "start": 0.10, "end": 0.34, "words": ["What", "is"]},
            {"target_index": 2, "text": "THIS LINK", "start": 0.40, "end": 0.72, "words": ["this", "link"]},
            {"target_index": 3, "text": "BRO", "start": 0.78, "end": 0.98, "words": ["bro"]},
        ]
        noisy_words = [
            {"word": "Where", "start": 0.11, "end": 0.23},
            {"word": "it", "start": 0.24, "end": 0.35},
            {"word": "those", "start": 0.43, "end": 0.55},
            {"word": "lane", "start": 0.56, "end": 0.75},
            {"word": "bruh", "start": 0.80, "end": 1.00},
        ]

        votes = retimer.model_votes_for_targets(
            "faster_whisper_small_en",
            noisy_words,
            [str(target["text"]) for target in canonical_targets],
            canonical_targets=canonical_targets,
        )

        self.assertEqual([vote["match_mode"] for vote in votes], ["same_index_temporal_anchor"] * 3)
        self.assertEqual([vote["text"] for vote in votes], ["WHAT IS", "THIS LINK", "BRO"])
        self.assertLessEqual(abs(float(votes[0]["start"]) - float(canonical_targets[0]["start"])), 0.05)

    def test_ensemble_retimer_prefers_majority_supported_canonical_source(self):
        from script import ensemble_retime_review_kits as retimer

        def timed_words(tokens, offset=0.0, gap_after=None):
            gap_after = set(gap_after or [])
            cursor = offset
            words = []
            for index, token in enumerate(tokens):
                start = cursor
                end = start + 0.16
                words.append({"word": token, "start": round(start, 3), "end": round(end, 3)})
                cursor = end + (0.46 if index in gap_after else 0.06)
            return words

        majority = ["Wait", "that", "is", "not", "extra", "Emily", "bear"]
        outlier = ["Bitch.", "homie", "I'm", "a", "bitch", "I'm", "a", "bitch", "that", "is", "not", "extra", "Emily", "bam"]
        source_word_sets = {
            "faster_whisper": timed_words(majority, offset=0.00, gap_after={0}),
            "faster_whisper_base_en": timed_words(majority, offset=0.02, gap_after={0}),
            "faster_whisper_small_en": timed_words(majority, offset=0.01, gap_after={0}),
            "faster_whisper_medium_en": timed_words(outlier, offset=0.00, gap_after={0}),
            "faster_whisper_distil_medium_en": timed_words(majority, offset=0.015, gap_after={0}),
        }

        canonical = retimer.preferred_canonical_source(source_word_sets, min_votes=3)

        self.assertEqual(canonical, "faster_whisper_distil_medium_en")

    def test_ensemble_retimer_rejects_truncated_existing_source_as_canonical(self):
        from script import ensemble_retime_review_kits as retimer

        def timed_words(tokens, offset=0.0):
            cursor = offset
            words = []
            for token in tokens:
                start = cursor
                end = start + 0.14
                words.append({"word": token, "start": round(start, 3), "end": round(end, 3)})
                cursor = end + 0.06
            return words

        full = [
            "this",
            "clip",
            "has",
            "enough",
            "words",
            "for",
            "the",
            "ensemble",
            "to",
            "agree",
            "without",
            "using",
            "the",
            "tiny",
            "old",
            "caption",
            "as",
            "the",
            "source",
            "truth",
        ]
        source_word_sets = {
            "faster_whisper": timed_words(["tiny", "old", "caption"]),
            "faster_whisper_base_en": timed_words(full, offset=0.00),
            "faster_whisper_small_en": timed_words(full, offset=0.01),
            "faster_whisper_medium_en": timed_words(full, offset=0.02),
            "faster_whisper_distil_medium_en": timed_words(full, offset=0.015),
        }

        canonical = retimer.preferred_canonical_source(source_word_sets, min_votes=3)

        self.assertEqual(canonical, "faster_whisper_distil_medium_en")

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
                "clip_created_at": (datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
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

    def test_visible_render_kits_use_sidecar_proof_without_live_ffprobe(self):
        kit_id = self.make_publishable_kit(approved=False)

        with mock.patch.object(db, "_actual_review_video_ok", side_effect=AssertionError("live ffprobe should not run")):
            visible = db.visible_render_kits()

        self.assertIn(kit_id, [item["id"] for item in visible])

    def test_auth_status_shape(self):
        payload = all_status()
        self.assertIn("twitch", payload["providers"])
        self.assertIn("kick", payload["providers"])
        self.assertIn("required_redirects", payload)
        raw = json.dumps(payload).lower()
        for provider in payload["providers"].values():
            self.assertIn(provider["client_secret"], {"configured", "missing"})
        self.assertNotIn("access_token", raw)

    def test_no_key_mode_blocks_credential_reads_and_refresh(self):
        with mock.patch.dict(os.environ, {"CLIPPING_OPS_NO_KEY": "1"}, clear=False):
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

    def test_campaign_project_records_use_sidecar_proof_without_live_ffprobe(self):
        self.make_publishable_kit(approved=False)

        with mock.patch.object(db, "_actual_review_video_ok", side_effect=AssertionError("live ffprobe should not run")):
            projects = db.campaign_project_records()

        yourrage = next(item for item in projects if item["slug"] == "yourrage")
        self.assertGreaterEqual(yourrage["rendered_count"], 1)

    def test_readiness_report_keeps_live_video_verification(self):
        self.make_publishable_kit(approved=False)

        with mock.patch.object(db, "_actual_review_video_ok", side_effect=AssertionError("readiness must live-verify video")):
            with self.assertRaises(AssertionError):
                db.readiness_report()

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
                        "caption_timeline": [
                            {
                                "start": 0.30,
                                "end": 0.72,
                                "text": "THIS IS",
                                "timing_mode": "ensemble_consensus",
                                "model_votes": 4,
                                "vote_spread_seconds": 0.08,
                            },
                            {
                                "start": 0.82,
                                "end": 1.24,
                                "text": "WHAT YOU",
                                "timing_mode": "ensemble_consensus",
                                "model_votes": 4,
                                "vote_spread_seconds": 0.08,
                            },
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(db._render_text_manifest_blockers(manifest), [])

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
                        "caption_beats": ["THIS IS"],
                        "caption_timeline": [
                            {
                                "start": 0.30,
                                "end": 0.72,
                                "text": "THIS IS",
                                "timing_mode": "strong_model_anchor",
                                "model_votes": 1,
                                "vote_spread_seconds": 0.0,
                            }
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("weak strong-anchor" in item for item in db._render_text_manifest_blockers(manifest)))

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
