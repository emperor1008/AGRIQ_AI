"""Compatibility entrypoint: ``app = create_app()`` (kept tiny by design)."""
from agriq import create_app

app = create_app()

if __name__ == "__main__":  # pragma: no cover
    app.run(debug=True)
