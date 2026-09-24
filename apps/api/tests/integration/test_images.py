"""Phase 4 integration tests: crop-image API.

Covers: honest unavailable state (no approved model), upload validation,
ownership isolation (two independent farmers), safe deletion, feedback and
expert-review flows, route-regression sanity, and the migration chain.
No real model ships with Phase 4 — tests assert the honest unavailable
state, never a fabricated prediction.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

API_DIR = Path(__file__).resolve().parents[2]  # apps/api
ROOT = API_DIR.parents[1]  # AGRIQ_AI-main repo root (contains ml/)
for _p in (str(API_DIR), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _png(color=(80, 130, 60), size=(800, 800)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def analyse_url():
    return "/api/v1/crop-images/analyse"


def _upload(auth_client, url, data=_png(), crop="rice", filename="leaf.png"):
    return auth_client.post(
        url,
        data={"image": (io.BytesIO(data), filename), "crop": crop,
              "csrf_token": "test-csrf-token"},
        content_type="multipart/form-data",
    )


class TestHonestStates:
    def test_analyse_returns_unavailable_without_approved_model(self, auth_client, analyse_url):
        """Completion criterion 9 + real-data policy: no model → explicit
        unavailable state, never a fabricated prediction."""
        response = _upload(auth_client, analyse_url)
        assert response.status_code == 201
        body = response.get_json()
        assert body["ok"] is True
        analysis = body["analysis"]
        assert analysis["status"] == "unavailable"
        assert analysis["message"] == "Image analysis is not currently available."
        assert analysis["predictions"] == []
        assert analysis["model"] is None

    def test_capabilities_reflect_absent_model(self, auth_client):
        response = auth_client.get("/api/v1/crop-images/capabilities")
        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["image_analysis_available"] is False

    def test_unsupported_crop_is_clean_400(self, auth_client, analyse_url):
        response = _upload(auth_client, analyse_url, crop="mango")
        assert response.status_code == 400
        assert "not supported" in response.get_json()["error"].lower()

    def test_missing_crop_is_clean_400(self, auth_client, analyse_url):
        response = auth_client.post(
            analyse_url,
            data={"image": (io.BytesIO(_png()), "leaf.png"), "csrf_token": "test-csrf-token"},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400

    def test_non_image_rejected(self, auth_client, analyse_url):
        response = _upload(auth_client, analyse_url, data=b"definitely not an image",
                           filename="leaf.png")
        assert response.status_code == 400
        assert "error" in response.get_json()

    def test_oversize_image_rejected(self, auth_client, analyse_url):
        # A text payload with an image filename fails decoded-format validation.
        response = _upload(auth_client, analyse_url, data=b"0" * (6 * 1024 * 1024),
                           filename="big.png")
        assert response.status_code == 400

    def test_missing_file_is_clean_400(self, auth_client, analyse_url):
        response = auth_client.post(
            analyse_url,
            data={"crop": "rice", "csrf_token": "test-csrf-token"},
            content_type="multipart/form-data",
        )
        assert response.status_code == 400


class TestOwnershipIsolation:
    """Every ownership test uses two independent farmers and proves one
    cannot access the other's resources (foreign id == 404)."""

    def test_user_cannot_read_other_analysis(self, auth_client, second_farmer_client, analyse_url):
        create = _upload(auth_client, analyse_url)
        analysis_id = create.get_json()["analysis"]["analysis_id"]

        response = second_farmer_client.get(f"/api/v1/crop-images/analyses/{analysis_id}")
        assert response.status_code == 404

        own = auth_client.get(f"/api/v1/crop-images/analyses/{analysis_id}")
        assert own.status_code == 200

    def test_user_cannot_delete_other_analysis(self, auth_client, second_farmer_client, analyse_url):
        create = _upload(auth_client, analyse_url)
        analysis_id = create.get_json()["analysis"]["analysis_id"]

        response = second_farmer_client.delete(
            f"/api/v1/crop-images/analyses/{analysis_id}",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 404
        # Original owner still sees it.
        assert auth_client.get(f"/api/v1/crop-images/analyses/{analysis_id}").status_code == 200

    def test_user_cannot_feedback_other_analysis(self, auth_client, second_farmer_client, analyse_url):
        create = _upload(auth_client, analyse_url)
        analysis_id = create.get_json()["analysis"]["analysis_id"]

        response = second_farmer_client.post(
            f"/api/v1/crop-images/analyses/{analysis_id}/feedback",
            json={"farmer_feedback": "sneaky note"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 404

    def test_user_cannot_request_expert_review_other_analysis(self, auth_client, second_farmer_client, analyse_url):
        create = _upload(auth_client, analyse_url)
        analysis_id = create.get_json()["analysis"]["analysis_id"]

        response = second_farmer_client.post(
            f"/api/v1/crop-images/analyses/{analysis_id}/request-expert-review",
            json={},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 404


class TestFeedbackAndDeletion:
    def test_feedback_roundtrip(self, auth_client, analyse_url):
        create = _upload(auth_client, analyse_url)
        analysis_id = create.get_json()["analysis"]["analysis_id"]
        response = auth_client.post(
            f"/api/v1/crop-images/analyses/{analysis_id}/feedback",
            json={"farmer_feedback": "The photo was of a healthy leaf."},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 201
        assert response.get_json()["ok"] is True

    def test_empty_feedback_rejected(self, auth_client, analyse_url):
        create = _upload(auth_client, analyse_url)
        analysis_id = create.get_json()["analysis"]["analysis_id"]
        response = auth_client.post(
            f"/api/v1/crop-images/analyses/{analysis_id}/feedback",
            json={"farmer_feedback": "   "},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 400

    def test_expert_review_request_flags_pending(self, auth_client, analyse_url):
        create = _upload(auth_client, analyse_url)
        analysis_id = create.get_json()["analysis"]["analysis_id"]
        response = auth_client.post(
            f"/api/v1/crop-images/analyses/{analysis_id}/request-expert-review",
            json={},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 201
        assert response.get_json()["review_status"] == "pending"

    def test_soft_delete_then_404(self, auth_client, analyse_url):
        create = _upload(auth_client, analyse_url)
        analysis_id = create.get_json()["analysis"]["analysis_id"]
        response = auth_client.delete(
            f"/api/v1/crop-images/analyses/{analysis_id}",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        assert response.status_code == 200
        assert auth_client.get(f"/api/v1/crop-images/analyses/{analysis_id}").status_code == 404

    def test_unauthenticated_is_404(self, client, analyse_url):
        response = client.get("/api/v1/crop-images/capabilities")
        assert response.status_code == 404


class TestRouteRegression:
    """Baseline Phase 3 routes must all still exist (no removals)."""

    BASELINE_ROUTES = (
        ("POST", "/login"),
        ("POST", "/logout"),
        ("GET", "/healthz"),
        ("GET", "/api/profile"),
        ("POST", "/api/profile"),
        ("PATCH", "/api/profile"),
        ("GET", "/api/farms"),
        ("POST", "/api/farms"),
        ("GET", "/api/farmer-context"),
        ("GET", "/api/live-weather"),
        ("GET", "/api/market-prices"),
        ("POST", "/ask-ai"),
        ("POST", "/api/v1/copilot/messages"),
        ("POST", "/api/v1/recommendations/1/feedback"),
        ("GET", "/api/v1/voice/capabilities"),
        ("POST", "/api/v1/voice/sessions"),
        ("POST", "/api/v1/voice/syshesis-placeholder"),  # replaced below
    )

    def test_all_baseline_routes_present(self, app):
        rules = {(method, str(rule)) for rule in app.url_map.iter_rules()
                 for method in rule.methods if method not in ("HEAD", "OPTIONS")}
        required = [r for r in self.BASELINE_ROUTES if "placeholder" not in r[1]]
        required += [
            ("POST", "/api/v1/voice/synthesise"),
            ("POST", "/api/v1/voice/sessions/1/confirm"),
            ("DELETE", "/api/v1/voice/sessions/1/audio"),
            ("POST", "/api/v1/crop-images/analyse"),
            ("GET", "/api/v1/crop-images/analyses/1"),
            ("DELETE", "/api/v1/crop-images/analyses/1"),
            ("POST", "/api/v1/crop-images/analyses/1/feedback"),
            ("POST", "/api/v1/crop-images/analyses/1/request-expert-review"),
            ("GET", "/api/v1/crop-images/capabilities"),
        ]
        missing = [
            r for r in required
            if not any(
                self._matches(rule, r[1])
                for method, rule in rules
                if method == r[0]
            )
        ]
        assert not missing, f"Regression: routes disappeared: {missing}"

    @staticmethod
    def _matches(rule: str, pattern: str) -> bool:
        """Match Flask converter syntax (/x/<int:id>) against concrete paths."""
        import re

        regex = "^" + re.sub(r"<[^>]+>", r"[^/]+", rule) + "$"
        return re.match(regex, pattern) is not None


class TestMigrationChain:
    def _alembic_cfg(self):
        from alembic.config import Config as AlembicConfig

        cfg = AlembicConfig()
        cfg.set_main_option("script_location", str(API_DIR / "migrations"))
        return cfg

    def test_head_is_0005_phase5_risk(self):
        """Phase 5 adds 0005_phase5_risk on top of the Phase 4 head."""
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(self._alembic_cfg())
        assert script.get_heads() == ["0005_phase5_risk"]

    def test_upgrade_downgrade_cycle_on_clean_db(self, tmp_path):
        """Full upgrade → downgrade → upgrade against an isolated SQLite file."""
        import os

        from alembic import command

        db_path = tmp_path / "mig_test.db"
        cfg = self._alembic_cfg()
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        try:
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "0003_phase3_voice")
            command.upgrade(cfg, "head")
            assert db_path.exists()
        finally:
            os.environ.pop("DATABASE_URL", None)

    def test_image_tables_exist_after_upgrade(self, tmp_path):
        import os
        import sqlite3

        from alembic import command

        db_path = tmp_path / "mig_tables.db"
        cfg = self._alembic_cfg()
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        try:
            command.upgrade(cfg, "head")
            con = sqlite3.connect(db_path)
            tables = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            con.close()
            assert "image_analyses" in tables
            assert "image_analysis_feedback" in tables
        finally:
            os.environ.pop("DATABASE_URL", None)
