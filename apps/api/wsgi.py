"""Production WSGI entrypoint for Gunicorn.

    gunicorn --chdir apps/api --bind 0.0.0.0:8000 --workers 2 --threads 4 wsgi:app
"""
from agriq import create_app

app = create_app()
