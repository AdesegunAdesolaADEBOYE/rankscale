# RankScale

RankScale is a programmatic SEO and lead-generation platform. It is being built with Django, PostgreSQL, Celery, Redis, and Docker.

## Current foundation

- Django application with a JSON health endpoint at `/api/health/`
- PostgreSQL database and Redis broker for local container-based development
- Celery worker process configured alongside the web service
- Pytest/Django smoke test
- SQLite fallback for running Django locally without PostgreSQL

## Run with Docker Compose

Requirements: Docker Desktop with Compose v2.

1. Copy `.env.example` to `.env` and replace `DJANGO_SECRET_KEY` with a private value.
2. Start the services with `docker compose up --build`.
3. Open `http://localhost:8000/api/health/`; a healthy response includes `{"status":"ok","database":"ok"}`.
4. Create an administrator with `docker compose exec web python manage.py createsuperuser`.

The Compose web service applies database migrations before starting. To run tests, use `docker compose exec web pytest`.

## Run Django directly

Use Python 3.11 or newer. Install Tesseract OCR 5 and its English language data on the machine that runs Celery (`tesseract-ocr` and `tesseract-ocr-eng` on Debian/Ubuntu; on Windows, install the Tesseract application and ensure `tesseract.exe` is on `PATH`). Create and activate a virtual environment, install `requirements.txt`, then run `python manage.py migrate` and `python manage.py runserver`. Without `DATABASE_URL`, Django uses a local SQLite database. Set `REDIS_URL` when dispatching Celery tasks.

## Services

| Service | Purpose |
| --- | --- |
| `web` | Django web application, port 8000 |
| `db` | PostgreSQL 16 database |
| `redis` | Celery message broker |
| `worker` | Asynchronous Celery worker |

## Dataset ingestion

Create a campaign and open its **Data** link from the dashboard. Upload CSV, XLSX, JSON, or PDF files, or paste a Google Sheets link. File and sheet imports are limited to 10 MB, 50 columns, and 100,000 rows. XLSX imports use the first worksheet. JSON must be a list of objects with the same keys. PDFs are imported as one text row per page. RankScale first extracts embedded text and runs Tesseract OCR on pages without extractable text. OCR recognizes printed text; scan quality and language affect accuracy. RankScale stores each imported row as JSON associated with the campaign. Import status, row count, column names, and errors appear on the campaign's dataset page. Failed imports can be retried after correcting the source or restoring the worker.

Google Sheets links that are publicly viewable can be imported without connecting an account. Private sheets are supported after connecting Google with the read-only Sheets scope. Enable the Google Sheets API and configure the OAuth consent screen in Google Cloud. Create a Google OAuth web application client, add the callback URL to its authorized redirect URIs, and set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and `GOOGLE_OAUTH_REDIRECT_URI` in `.env`. The example callback is `http://localhost:8000/integrations/google/callback/`; set it to the exact local or deployed URL you use. OAuth refresh tokens are encrypted with Django's `SECRET_KEY`, so keep that key stable and private.

Dataset imports run in a Celery worker. Start Redis and the worker before uploading:

```sh
docker compose up --build
```

For a direct Django run, set `REDIS_URL`, then start a worker in a second terminal with `celery -A config worker --loglevel=info`.

## Next product areas

Content templates, generated pages, tenant isolation, and lead capture are planned domain features and will be added incrementally.
