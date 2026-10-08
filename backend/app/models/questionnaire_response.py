from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, utc_now


class QuestionnaireResponse(IdMixin, TimestampMixin, Base):
    __tablename__ = "questionnaire_responses"

    patient_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("patients.id"),
        nullable=False,
        index=True,
    )

    encounter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("encounters.id"),
        nullable=False,
        index=True,
    )

    scale_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    item_scores_json: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
    )

    total_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )
