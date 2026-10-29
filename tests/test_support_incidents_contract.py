"""Contract and tenant authorization regression for the incident center."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.support_incident import SupportIncident
from app.schemas.support_incident import IncidentCreate, IncidentUpdate
from app.services.support_incidents import _as_output


def test_reference_rejects_non_hex_and_unbounded_text():
    with pytest.raises(ValidationError):
        IncidentCreate(
            title="Erreur", description="Impossible de valider un bulletin", reference="../secrets"
        )
    with pytest.raises(ValidationError):
        IncidentCreate(title="Erreur", description="x" * 2500)


def test_status_is_a_controlled_vocabulary():
    with pytest.raises(ValidationError):
        IncidentUpdate(status="run arbitrary code")


def test_incident_does_not_expose_backend_diagnostics():
    item = SupportIncident(
        id="a" * 32,
        reference="AB12CD34EF56",
        title="Erreur serveur",
        description="Incident détecté automatiquement",
        source="backend",
        status="new",
        priority="high",
    )
    item.created_at = datetime(2026, 10, 29)
    item.updated_at = datetime(2026, 10, 29)
    result = _as_output(item)
    assert "traceback" not in result.model_dump()
    assert set(result.model_dump()) == {
        "id",
        "reference",
        "title",
        "description",
        "source",
        "status",
        "priority",
        "created_at",
        "updated_at",
        "resolved_at",
        "events",
    }
