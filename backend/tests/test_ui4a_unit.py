"""UI-4A: строгие контракты без имитации ответа AI."""

from uuid import uuid4

import pytest
from app.schemas.ai_workspace import AIRequestCreate, AIRequestRead, AIWorkspaceInfo
from pydantic import ValidationError


def test_request_validates_question_and_unique_attachments():
    key = uuid4()
    item = AIRequestCreate(request_key=key, question="  Проанализировать клиническую динамику  ")
    assert item.question == "Проанализировать клиническую динамику"
    assert item.attachment_ids == []
    with pytest.raises(ValidationError):
        AIRequestCreate(request_key=key, question="  кратко  ")
    with pytest.raises(ValidationError):
        AIRequestCreate(request_key=key, question="Клиническая динамика", attachment_ids=[key, key])
    with pytest.raises(ValidationError):
        AIRequestCreate(request_key=key, question="Клиническая динамика", injection="bad")
    with pytest.raises(ValidationError):
        AIRequestCreate(request_key="not-a-uuid", question="Клиническая динамика")


def test_workspace_is_explicitly_offline():
    status = AIWorkspaceInfo()
    assert status.dispatch_enabled is False
    assert status.llm_connected is False
    assert status.attachment_content_allowed is False
    assert "response" not in AIRequestRead.model_fields
    assert AIRequestRead.model_fields["status"].default == "prepared"
