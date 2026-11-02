from apps.audit.models import AuditEvent


def record_event(
    *, action: str, entity_type: str, company=None, user=None, entity_id="", **metadata
):
    return AuditEvent.objects.create(
        action=action,
        entity_type=entity_type,
        company=company,
        user=user,
        entity_id=str(entity_id),
        metadata=metadata,
    )
