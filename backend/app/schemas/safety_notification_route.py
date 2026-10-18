"""Публичная настройка собственного внутреннего маршрута без адреса доставки."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class NotificationRouteChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["in_app"] = "in_app"
    enabled: bool


class NotificationRouteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    patient_id: str
    recipient_user_id: str
    channel: Literal["in_app"]
    enabled: bool
    confirmed_at: datetime | None
