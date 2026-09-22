"""AGRIQ AI Flask application package.

Exposes the application factory :func:`create_app` which assembles
configuration, extensions, domain services and HTTP blueprints.
"""
from __future__ import annotations

from .app_factory import create_app

__all__ = ["create_app"]
