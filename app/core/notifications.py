"""Notification placeholder.

This project is a control-plane; it intentionally does not implement email/SMS/etc.
These helpers provide a single call-site for future integrations (Slack, email,
webhook, event bus), while defaulting to structured logging.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def notify(
    event: str,
    *,
    entity_type: str,
    entity_id: str,
    actor: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Emit a notification event.

    Current behavior: logs a structured message.
    """

    logger.info(
        "notify:%s",
        event,
        extra={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor": actor,
            "details": details or {},
        },
    )
