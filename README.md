# rankscale
RankScale is an enterprise-grade programmatic SEO and lead-generation SaaS built with Python, Django, PostgreSQL, Celery, and Docker. It automates high-volume landing page generation, dataset mapping, and conversion tracking for modern businesses.

RankScale: Enterprise-Grade Programmatic SEO & Lead Generation Hub

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.0%2B-green.svg)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-orange.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> *RankScale* is a high-performance, multi-tenant content marketing and programmatic SEO (pSEO) platform. It empowers businesses to scale organic search traffic by seamlessly bridging structured tabular datasets with automated AI content generation, multi-channel publishing pipelines, and conversion-optimized lead capture hooks.

---

## 🏗️ System Architecture & Data Flow

RankScale uses a decoupled, asynchronous processing model to handle heavy programmatic generation tasks without choking web server threads.

```mermaid
graph TD
    User([User / Web Browser]) -->|HTTPS / REST API| NGINX[NGINX Reverse Proxy]
    NGINX --> Django[Django Backend API Server]
    
    subgraph Core Application Cluster
        Django -->|ORM Queries| Postgres[(PostgreSQL Database)]
        Django -->|Session / Cache| Redis[(Redis Broker)]
        Django -->|Dispatch Async Jobs| Celery[Celery Worker Cluster]
    end

    subgraph External Integrations
        Celery -->|Prompt / Token Generation| OpenAI[OpenAI / Anthropic APIs]
        Celery -->|Push Published Pages| WP[WordPress REST APIs / Webhooks]
    end

    Postgres -.->|Data Persistence| Backup[(Automated Cloud Backups)]

📊 Entity-Relationship (ER) Database Schema
erDiagram
    User ||--o{ Campaign : "owns"
    Campaign ||--o{ Dataset : "contains"
    Campaign ||--o{ ContentTemplate : "utilizes"
    Campaign ||--o{ GeneratedPage : "produces"
    ContentTemplate ||--o{ GeneratedPage : "templates"
    GeneratedPage ||--o{ LeadSubmission : "captures"

    User {
        uuid id PK
        string email
        string username
        datetime created_at
    }

    Campaign {
        uuid id PK
        uuid user_id FK
        string name
        url target_domain
        boolean is_active
        datetime created_at
    }

    Dataset {
        uuid id PK
        uuid campaign_id FK
        string file_name
        json raw_data
        int row_count
        datetime created_at
    }

    ContentTemplate {
        uuid id PK
        uuid campaign_id FK
        string title_pattern
        text meta_description
        text body_markdown
        datetime created_at
    }

    GeneratedPage {
        uuid id PK
        uuid campaign_id FK
        uuid template_id FK
        string slug UK
        string rendered_title
        text rendered_body
        float seo_score
        string status
        datetime created_at
    }

    LeadSubmission {
        uuid id PK
        uuid page_id FK
        string visitor_email
        string visitor_name
        json payload_data
        datetime created_at
    }

🛠️ Technology Stack
 * Backend Framework: Python, Django, Django REST Framework (DRF)
 * Asynchronous Processing: Celery, Redis (Message Broker & Cache)
 * Database & Persistence: PostgreSQL (Relational JSON Storage for matrices)
 * Containerization & Devops: Docker, Docker Compose
 * Testing & Quality: Pytest, Pytest-Django
🚀 Getting Started Locally (Dockerized Setup)
To spin up the entire application stack (Django, PostgreSQL, Redis, and Celery workers) with a single command, ensure you have Docker and Docker Compose installed on your machine.
 * Clone the repository:
   git clone [https://github.com/AdesegunAdesolaADEBOYE/rankscale.git](https://github.com/AdesegunAdesolaADEBOYE/rankscale.git)
cd rankscale

 * Configure environment variables:
   Create a .env file in the root directory based on your configuration parameters:
   DEBUG=True
SECRET_KEY=your-super-secret-django-key
DATABASE_URL=postgres://postgres:postgres@db:5432/rankscale_db
REDIS_URL=redis://redis:6379/0

 * Build and launch containers:
   docker compose up --build

 * Run database migrations inside the container:
   docker compose exec web python manage.py migrate

 * Access the application:
   * API Server: http://localhost:8000
   * Admin Dashboard: http://localhost:8000/admin
🧪 Running Tests
RankScale incorporates automated test suites to ensure business logic reliability and model integrity.
docker compose exec web pytest

💡 Core Features
 * Multi-Tenant Campaign Management: Isolate data structures and publishing configurations securely across distinct client workspaces using Role-Based Access Control (RBAC).
 * Programmatic SEO (pSEO) Matrix Ingestion: Upload structured CSV/XLSX datasets into relational PostgreSQL JSON fields to map long-tail keyword combinations at scale.
 * Asynchronous Page Generation Engine: Offloads heavy batch rendering loops and LLM API calls to background Celery workers, preventing server timeouts.
 * Conversion Analytics & Lead Hook Tracking: Capture verified inbound form submissions mapped directly back to individual generated landing pages.
👤 Author
Adesegun Adesola Adeboye
 * Portfolio: adesegunadeboye.com.ng
 * LinkedIn: Adesegun Adeboye
 * GitHub: @AdesegunAdesolaADEBOYE
📝 License
This project is open-source under the MIT License.
