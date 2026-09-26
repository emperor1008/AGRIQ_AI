"""Offline project validation for the restructured AGRIQ AI.

Checks required files, Python syntax of every backend module, absence of
hard-coded secrets, and (when Flask is importable) that create_app()
exposes all legacy routes.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"

REQUIRED = [
    "apps/api/agriq/__init__.py",
    "apps/api/agriq/app_factory.py",
    "apps/api/agriq/extensions.py",
    "apps/api/agriq/core/config.py",
    "apps/api/agriq/core/security.py",
    "apps/api/agriq/core/exceptions.py",
    "apps/api/agriq/api/auth.py",
    "apps/api/agriq/api/dashboard.py",
    "apps/api/agriq/api/assistant.py",
    "apps/api/agriq/api/weather.py",
    "apps/api/agriq/api/health.py",
    "apps/api/agriq/api/errors.py",
    "apps/api/agriq/domain/catalogs/crops.py",
    "apps/api/agriq/domain/catalogs/districts.py",
    "apps/api/agriq/domain/catalogs/diseases.py",
    "apps/api/agriq/domain/catalogs/pests.py",
    "apps/api/agriq/domain/catalogs/soils.py",
    "apps/api/agriq/domain/catalogs/education.py",
    "apps/api/agriq/domain/risk/scoring.py",
    "apps/api/agriq/domain/risk/explanations.py",
    "apps/api/agriq/domain/risk_engine/base.py",
    "apps/api/agriq/domain/risk_engine/analyzers.py",
    "apps/api/agriq/domain/risk_engine/thresholds.py",
    "apps/api/agriq/domain/risk_evaluation/definitions.py",
    "apps/api/agriq/domain/risk_evaluation/dataset.py",
    "apps/api/agriq/domain/risk_evaluation/metrics.py",
    "apps/api/agriq/domain/risk_evaluation/evaluate.py",
    "apps/api/agriq/cli/evaluate_risk.py",
    "apps/api/agriq/api/risk.py",
    "apps/api/agriq/services/risk_service.py",
    "apps/api/agriq/repositories/risk_repository.py",
    "apps/api/agriq/services/farm_intelligence.py",
    "apps/api/agriq/services/student_intelligence.py",
    "apps/api/agriq/services/leaf_analysis.py",
    "apps/api/agriq/services/weather_advisory.py",
    "apps/api/agriq/services/assistant_orchestrator.py",
    "apps/api/agriq/integrations/weather/open_meteo.py",
    "apps/api/agriq/integrations/ai/gemini.py",
    "apps/api/agriq/integrations/market/agmarknet.py",
    "apps/api/agriq/integrations/maps/openstreetmap.py",
    "apps/api/agriq/templates/base.html",
    "apps/api/agriq/templates/auth/login.html",
    "apps/api/agriq/templates/auth/choose.html",
    "apps/api/agriq/templates/dashboard/index.html",
    "apps/api/agriq/templates/components/_macros.html",
    "apps/api/app.py",
    "apps/api/wsgi.py",
    "apps/api/requirements.txt",
    "apps/api/Dockerfile",
    "apps/api/tests/conftest.py",
    "apps/web/static/manifest.json",
    "apps/web/static/sw.js",
    "apps/web/README.md",
    "infrastructure/docker/docker-compose.yml",
    "infrastructure/nginx/nginx.conf",
    "scripts/validate_project.py",
    "scripts/check_environment.py",
    "scripts/run_tests.py",
    "docs/TECHNICAL_ARCHITECTURE.md",
    "docs/risk-engine.md",
    "docs/risk-evaluation.md",
    "docs/risk-api.md",
    "apps/web/static/js/risk-panel.js",
    ".env.example",
    ".gitignore",
    "docker-compose.yml",
    "README.md",
    "run.py",
]

LEGACY_ROUTES = ["/", "/login", "/choose", "/choose-mode", "/dashboard",
                 "/ask-ai", "/api/live-weather", "/logout", "/healthz"]

SECRET_PATTERN = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})")


def main() -> int:
    errors: list[str] = []

    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            errors.append(f"Missing: {rel}")

    # Python syntax across the API package
    py_files = list(API_ROOT.rglob("*.py"))
    for py in py_files:
        try:
            ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            errors.append(f"Python syntax error in {py.relative_to(ROOT)}: {exc}")

    # No hard-coded secrets
    for py in py_files:
        match = SECRET_PATTERN.search(py.read_text(encoding="utf-8"))
        if match:
            errors.append(f"Secret-like literal in {py.relative_to(ROOT)}")

    # CSS module split intact
    for css in ["tokens", "base", "components", "dashboard", "animations", "responsive"]:
        path = ROOT / "apps/web/static/css" / f"{css}.css"
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"CSS module missing/empty: {css}.css")

    # Route compatibility (requires Flask installed)
    try:
        sys.path.insert(0, str(API_ROOT))
        from agriq import create_app
        from agriq.core.config import TestingConfig

        app = create_app(TestingConfig())
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        for route in LEGACY_ROUTES:
            if route not in rules:
                errors.append(f"Legacy route missing: {route}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"Application factory check failed: {exc}")

    if errors:
        print("AGRIQ AI validation FAILED")
        print("\n".join(f"- {e}" for e in errors))
        return 1

    print("AGRIQ AI validation PASSED")
    print(f"Checked {len(REQUIRED)} required files, {len(py_files)} Python modules, "
          f"{len(LEGACY_ROUTES)} legacy routes, 6 CSS modules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
