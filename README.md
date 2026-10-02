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

Use Python 3.11 or newer. Create and activate a virtual environment, install `requirements.txt`, then run `python manage.py migrate` and `python manage.py runserver`. Without `DATABASE_URL`, Django uses a local SQLite database. Set `REDIS_URL` when dispatching Celery tasks.

## Services

| Service | Purpose |
| --- | --- |
| `web` | Django web application, port 8000 |
| `db` | PostgreSQL 16 database |
| `redis` | Celery message broker |
| `worker` | Asynchronous Celery worker |

## Next product areas

Campaigns, dataset ingestion, content templates, generated pages, tenant isolation, and lead capture are planned domain features and will be added incrementally.
