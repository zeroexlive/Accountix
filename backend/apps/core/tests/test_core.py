import pytest
from django.urls import reverse


def test_health_endpoint(client):
    resp = client.get(reverse("health"))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.django_db
def test_audit_event_record(db):
    from apps.audit.services import record_event

    event = record_event(action="test", entity_type="Company", entity_id="1")
    assert event.pk and event.action == "test"
