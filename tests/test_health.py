import pytest
from django.test import Client


@pytest.mark.django_db
def test_health_endpoint_reports_database_status():
    response = Client().get("/api/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}