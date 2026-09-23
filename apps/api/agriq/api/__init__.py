"""HTTP API layer: Flask blueprints for auth, dashboard, assistant, weather, health,
copilot (Phase 2), voice (Phase 3), images (Phase 4), farmer data and errors."""

from . import copilot, health, auth, dashboard, assistant, weather, voice, images, errors  # noqa: F401
