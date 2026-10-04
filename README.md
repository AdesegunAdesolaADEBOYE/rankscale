# RankScale

RankScale is a programmatic SEO and lead-generation platform. It is being built with Django, PostgreSQL, Celery, Redis, and Docker.

## Current foundation

- Django application with a JSON health endpoint at `/api/health/`
- PostgreSQL database and Redis broker for local container-based development
- Celery worker process configured alongside the web service
- Pytest/Django smoke test
- SQLite fallback for running Django locally without PostgreSQL
- Workspace-scoped campaigns, content templates, generated pages, and leads
- Workspace owner/admin/member roles with membership management for existing accounts

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

## Workspaces and team access

Every user has a personal workspace. Use **Workspace & members** in the sidebar to create additional workspaces and switch between those where you are a member. Owners can add existing RankScale users as admins or members; admins can add members. Campaigns, datasets, templates, generated pages, and leads are scoped to the selected workspace. An admin can remove members, while only the owner can remove admins; the owner membership cannot be removed.

Workspace invitations are sent to email addresses and expire after seven days. Invitees must sign in or create a RankScale account with the invited email address and explicitly accept the invitation. Configure `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and the TLS/SSL options in `.env` for SMTP delivery. The development default writes messages to the web process console; the `.env.example` SMTP host is a placeholder and must be replaced with your provider’s settings. Owners can edit roles, transfer ownership to a current member, and delete a workspace after typing its name to confirm; deleting a workspace permanently deletes its data.

## Content templates and generated page variables

Create or edit a template from **Templates**. Template variables are declared one per line using `name | label | default value | required`, such as `headline | Main headline | Grow with confidence | required`. Variables written in the template body as `{{ headline }}` are detected automatically. Campaign name, brand name, company name, target keyword, and website URL are supplied from the selected campaign. When generating a page, select a template to load its variable fields, fill required values, and generate the draft. Each page stores both the entered values and the rendered content so later template edits do not rewrite existing drafts.

Google Sheets links that are publicly viewable can be imported without connecting an account. Private sheets are supported after connecting Google with the read-only Sheets scope. Enable the Google Sheets API and configure the OAuth consent screen in Google Cloud. Create a Google OAuth web application client, add the callback URL to its authorized redirect URIs, and set `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and `GOOGLE_OAUTH_REDIRECT_URI` in `.env`. The example callback is `http://localhost:8000/integrations/google/callback/`; set it to the exact local or deployed URL you use. OAuth refresh tokens are encrypted with Django's `SECRET_KEY`, so keep that key stable and private.

Dataset imports run in a Celery worker. Start Redis and the worker before uploading:

```sh
docker compose up --build
```

For a direct Django run, set `REDIS_URL`, then start a worker in a second terminal with `celery -A config worker --loglevel=info`.

Generated pages remain drafts; public page publishing and deployment remain future work. Lead capture is available as a workspace-scoped MVP feature; lead pipeline stages remain future work.
