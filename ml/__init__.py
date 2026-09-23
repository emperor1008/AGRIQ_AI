"""AGRIQ AI machine-learning workspace (Phase 4).

Deliberately separate from the web application package (``agriq``): training
dependencies are never installed into the lightweight production-inference
environment, and nothing here executes at web-app start.
"""
