"""UI-4B: транзакционное ручное согласование ТОЛЬКО синтетических предложений."""

import hashlib
import json
import os
from uuid import UUID, uuid5

from app.clinical.demo_test_catalog import definition
from app.core.config import settings
from app.db.base import utc_now
from app.models.ai_review import AIReviewCase, AIReviewEvent, AIReviewVersion
from app.models.ai_workspace import AIRequest
from app.models.clinical_order import ClinicalOrder
from app.models.patient import Patient
from app.models.questionnaire_assignment import (
    QuestionnaireAssignment,
    QuestionnaireAssignmentAudit,
)
from app.schemas.ai_review import DraftImport, DraftRead, RejectDraft, ReviewAction, ReviewCommit
from app.schemas.clinical_order import OrderDraftCreate
from app.services.ai_agent_context import current_orders_match
from app.services.clinical_order import _audit as audit_order
from app.services.clinical_order import _check_ready
from app.services.context_builder import ContextBuilder
from app.services.doctor_settings import read_doctor_context
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _enabled() -> bool:
    return (
        settings.app_env != "production"
        and os.getenv("AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS", "0") == "1"
    )


def enabled_for_patient(db: Session, patient_id: str) -> bool:
    patient = db.get(Patient, patient_id)
    return bool(
        _enabled()
        and patient is not None
        and patient.deleted_at is None
        and isinstance(patient.demographics_json, dict)
        and patient.demographics_json.get("synthetic") is True
    )


def _require_demo(db: Session, patient_id: str) -> None:
    if not enabled_for_patient(db, patient_id):
        raise HTTPException(403, "Тестовые AI-черновики выключены или пациент не синтетический")


def _request(db: Session, request_id: str, doctor_id: str, patient_id: str) -> AIRequest:
    row = db.scalar(
        select(AIRequest).where(
            AIRequest.id == request_id,
            AIRequest.doctor_id == doctor_id,
            AIRequest.patient_id == patient_id,
        )
    )
    if row is None:
        raise HTTPException(404, "Подготовленный запрос не найден")
    return row


def _case(db: Session, request_id: str, lock: bool = False) -> AIReviewCase:
    stmt = select(AIReviewCase).where(AIReviewCase.request_id == request_id)
    if lock:
        stmt = stmt.with_for_update()
    case = db.scalar(stmt)
    if case is None:
        raise HTTPException(404, "Структурированный черновик не найден")
    return case


def _version(db: Session, case: AIReviewCase) -> AIReviewVersion:
    row = db.scalar(
        select(AIReviewVersion).where(
            AIReviewVersion.case_id == case.id, AIReviewVersion.version == case.current_version
        )
    )
    if row is None:
        raise HTTPException(409, "Версия структурированного черновика недоступна")
    return row


def _event(db: Session, case: AIReviewCase, doctor_id: str, action: str, data: dict) -> None:
    db.add(
        AIReviewEvent(
            case_id=case.id,
            actor_id=doctor_id,
            version=case.current_version,
            action=action,
            payload_json=data,
        )
    )


def _read(db: Session, case: AIReviewCase) -> DraftRead:
    versions = db.scalars(
        select(AIReviewVersion.version)
        .where(AIReviewVersion.case_id == case.id)
        .order_by(AIReviewVersion.version)
    ).all()
    return DraftRead(
        case_id=case.id,
        request_id=case.request_id,
        status=case.status,
        version=case.current_version,
        proposals=_version(db, case).proposals_json,
        versions_available=list(versions),
        approved_result=case.approved_result,
    )


def get_draft(db: Session, patient_id: str, doctor_id: str, request_id: str) -> DraftRead:
    _require_demo(db, patient_id)
    _request(db, request_id, doctor_id, patient_id)
    return _read(db, _case(db, request_id))


def get_historical_version(
    db: Session, patient_id: str, doctor_id: str, request_id: str, version: int
) -> DraftRead:
    _require_demo(db, patient_id)
    _request(db, request_id, doctor_id, patient_id)
    case = _case(db, request_id)
    row = db.scalar(
        select(AIReviewVersion).where(
            AIReviewVersion.case_id == case.id,
            AIReviewVersion.version == version,
        )
    )
    if row is None:
        raise HTTPException(404, "Историческая версия не найдена")
    all_versions = db.scalars(
        select(AIReviewVersion.version)
        .where(AIReviewVersion.case_id == case.id)
        .order_by(AIReviewVersion.version)
    ).all()
    return DraftRead(
        case_id=case.id,
        request_id=request_id,
        status="historical",
        version=version,
        proposals=row.proposals_json,
        versions_available=list(all_versions),
    )


def import_draft(
    db: Session, patient_id: str, doctor_id: str, request_id: str, payload: DraftImport
) -> DraftRead:
    _require_demo(db, patient_id)
    _request(db, request_id, doctor_id, patient_id)
    case = db.scalar(
        select(AIReviewCase).where(AIReviewCase.request_id == request_id).with_for_update()
    )
    if case is None:
        if payload.expected_version is not None:
            raise HTTPException(409, "Начальная версия ещё не создана")
        case = AIReviewCase(request_id=request_id, current_version=1, status="open")
        db.add(case)
        db.flush()
        action = "imported_test"
    else:
        if case.status != "open" or payload.expected_version != case.current_version:
            raise HTTPException(409, "Версия или статус изменились")
        case.current_version += 1
        action = "revised_test"
    data = [item.model_dump(mode="json") for item in payload.proposals]
    db.add(
        AIReviewVersion(
            case_id=case.id,
            version=case.current_version,
            created_by_id=doctor_id,
            origin="synthetic_manual_test",
            proposals_json=data,
        )
    )
    _event(db, case, doctor_id, action, {"proposal_count": len(data)})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Конфликт создания или версии черновика") from exc
    return _read(db, case)


def _fingerprint(db: Session, patient_id: str) -> str:
    """Фиксируем и назначения, которых ещё нет в исходном Context Builder."""
    orders = db.execute(
        select(
            ClinicalOrder.id,
            ClinicalOrder.version,
            ClinicalOrder.status,
        )
        .where(ClinicalOrder.patient_id == patient_id)
        .order_by(ClinicalOrder.id)
    ).all()
    tests = db.execute(
        select(
            QuestionnaireAssignment.id,
            QuestionnaireAssignment.revision,
            QuestionnaireAssignment.status,
        )
        .where(QuestionnaireAssignment.patient_id == patient_id)
        .order_by(QuestionnaireAssignment.id)
    ).all()
    return _sha({"orders": [list(x) for x in orders], "tests": [list(x) for x in tests]})


def _sha(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    ).hexdigest()


def _fresh(db: Session, request: AIRequest) -> None:
    current = ContextBuilder(db).build(request.patient_id)
    if current.content_sha256 != request.context_sha256:
        raise HTTPException(409, "Клинический контекст изменён: создайте новый AI-запрос")
    settings = read_doctor_context(db, request.doctor_id).model_dump(mode="json")
    if settings != request.doctor_context_json:
        raise HTTPException(409, "Настройки врача изменены: создайте новый AI-запрос")
    if not current_orders_match(db, request):
        raise HTTPException(409, "Список назначений изменён: создайте новый AI-запрос")


def _prepare(db: Session, case: AIReviewCase, request: AIRequest, payload: ReviewAction) -> dict:
    if case.status != "open" or case.current_version != payload.expected_version:
        raise HTTPException(409, "Черновик изменён или уже рассмотрен")
    proposals = {item["id"]: item for item in _version(db, case).proposals_json}
    selections = []
    alt_groups: set[str] = set()
    changed = False
    for entry in payload.selections:
        item = proposals.get(str(entry.proposal_id))
        if item is None:
            raise HTTPException(422, "Неизвестное предложение")
        group = item.get("alternative_group")
        if group:
            if group in alt_groups:
                raise HTTPException(422, "Нельзя одновременно одобрить альтернативные предложения")
            alt_groups.add(group)
        if item["kind"] == "demo_test":
            if entry.order is not None or (
                entry.test_id is not None and entry.test_id != item["test_id"]
            ):
                raise HTTPException(422, "Тест можно выбрать, но не заменить другим")
            definition(item["test_id"])
            data = {"test_id": item["test_id"], "test_version": definition(item["test_id"]).version}
            edited = False
            table = "questionnaire_assignments"
        else:
            if entry.test_id is not None:
                raise HTTPException(422, "Неверный тип редактирования")
            order = entry.order or OrderDraftCreate.model_validate(item["order"])
            if order.kind != item["kind"]:
                raise HTTPException(422, "Нельзя изменять вид назначения")
            edited = order.model_dump(mode="json") != item["order"]
            data = order.model_dump(mode="json")
            data["request_key"] = str(uuid5(UUID(case.id), item["id"]))
            model = ClinicalOrder(
                **order.model_dump(exclude={"request_key"}),
                request_key=data["request_key"],
                patient_id=request.patient_id,
                author_id=request.doctor_id,
                status="draft",
                version=1,
            )
            _check_ready(model)
            table = "clinical_orders"
        changed |= edited
        selections.append(
            {
                "proposal_id": item["id"],
                "table": table,
                "original": item["order"]
                if item["kind"] != "demo_test"
                else {"test_id": item["test_id"]},
                "final": data,
                "edited": edited,
                "alternative_group": group,
            }
        )
    if changed and not (payload.edit_reason and len(payload.edit_reason.strip()) >= 3):
        raise HTTPException(422, "Укажите причину изменения AI-предложения")
    _fresh(db, request)
    body = {
        "case_id": case.id,
        "version": case.current_version,
        "request_id": request.id,
        "context_sha256": request.context_sha256,
        "current_records_sha256": _fingerprint(db, request.patient_id),
        "changes": selections,
        "edit_reason": payload.edit_reason if changed else None,
    }
    body["preview_sha256"] = _sha(body)
    return body


def preview(
    db: Session, patient_id: str, doctor_id: str, request_id: str, payload: ReviewAction
) -> dict:
    _require_demo(db, patient_id)
    request = _request(db, request_id, doctor_id, patient_id)
    return _prepare(db, _case(db, request_id), request, payload)


def approve(
    db: Session, patient_id: str, doctor_id: str, request_id: str, payload: ReviewCommit
) -> dict:
    _require_demo(db, patient_id)
    request = _request(db, request_id, doctor_id, patient_id)
    case = _case(db, request_id, lock=True)
    if case.status == "approved" and case.approved_hash == payload.preview_sha256:
        return case.approved_result
    summary = _prepare(db, case, request, payload)
    if summary["preview_sha256"] != payload.preview_sha256:
        raise HTTPException(409, "Предварительный просмотр устарел; обновите его")
    results = []
    try:
        for item in summary["changes"]:
            unique_key = str(uuid5(UUID(case.id), item["proposal_id"]))
            if item["table"] == "clinical_orders":
                data = OrderDraftCreate.model_validate(item["final"])
                row = ClinicalOrder(
                    **data.model_dump(exclude={"request_key"}),
                    request_key=unique_key,
                    patient_id=patient_id,
                    author_id=doctor_id,
                    status="approved",
                    version=1,
                    approved_by_id=doctor_id,
                    approved_at=utc_now(),
                )
                _check_ready(row)
                db.add(row)
                db.flush()
                audit_order(db, row, doctor_id, "ai_review_approved")
            else:
                row = QuestionnaireAssignment(
                    patient_id=patient_id,
                    assigned_by_id=doctor_id,
                    request_key=unique_key,
                    test_id=item["final"]["test_id"],
                    test_version=item["final"]["test_version"],
                    status="assigned",
                    revision=1,
                )
                db.add(row)
                db.flush()
                db.add(
                    QuestionnaireAssignmentAudit(
                        assignment_id=row.id,
                        actor_id=doctor_id,
                        action="ai_review_assigned",
                        revision=1,
                        snapshot_json={
                            "test_id": row.test_id,
                            "status": row.status,
                            "ai_review_case_id": case.id,
                        },
                    )
                )
            results.append(
                {"proposal_id": item["proposal_id"], "table": item["table"], "id": row.id}
            )
        case.status = "approved"
        case.approved_hash = summary["preview_sha256"]
        case.approved_result = {
            "status": "approved",
            "records": results,
            "preview_sha256": case.approved_hash,
        }
        _event(
            db,
            case,
            doctor_id,
            "approved",
            {
                "results": results,
                "edited": [x["proposal_id"] for x in summary["changes"] if x["edited"]],
                "edit_reason": summary["edit_reason"],
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Конкурирующая запись назначения; обновите предпросмотр") from exc
    except Exception:
        db.rollback()
        raise
    return case.approved_result


def reject(
    db: Session, patient_id: str, doctor_id: str, request_id: str, payload: RejectDraft
) -> DraftRead:
    _require_demo(db, patient_id)
    _request(db, request_id, doctor_id, patient_id)
    case = _case(db, request_id, lock=True)
    if case.status != "open" or case.current_version != payload.expected_version:
        raise HTTPException(409, "Версия или статус изменились")
    case.status = "rejected"
    _event(db, case, doctor_id, "rejected", {"reason": payload.reason})
    db.commit()
    return _read(db, case)
