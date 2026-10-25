"""Транзакционное врачебное согласование структурированных предложений."""

import hashlib
import json
from uuid import UUID, uuid5

from app.clinical.demo_test_catalog import definition
from app.db.base import utc_now
from app.models.ai_demo_bridge import AIDemoAnalysis
from app.models.ai_review import AIReviewCase, AIReviewEvent, AIReviewVersion
from app.models.ai_workspace import AIRequest
from app.models.clinical_entry_audit import ClinicalEntryAudit
from app.models.clinical_order import ClinicalOrder
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalObservation
from app.models.patient import Patient
from app.models.questionnaire_assignment import (
    QuestionnaireAssignment,
    QuestionnaireAssignmentAudit,
)
from app.schemas.ai_demo_bridge import DemoAnalysisSubmit
from app.schemas.ai_review import (
    ClinicianOrderSupplement,
    DraftImport,
    DraftRead,
    Proposal,
    RejectDraft,
    ReviewAction,
    ReviewCommit,
)
from app.schemas.ai_structured_proposals import StructuredProposalSubmit
from app.schemas.clinical_entry import ManualHistoryCreate, ManualObservationCreate
from app.schemas.clinical_order import OrderDraftCreate
from app.services.ai_agent_context import current_orders_match
from app.services.clinical_entries import _encounter
from app.services.clinical_order import _audit as audit_order
from app.services.clinical_order import _check_ready
from app.services.context_builder import ContextBuilder
from app.services.doctor_settings import read_doctor_context
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def enabled_for_patient(db: Session, patient_id: str) -> bool:
    """Совместимый с ai-workspace.v1 признак доступности review.

    Авторизация врача и принадлежность пациента проверяются в маршруте.
    Демонстрационный маркер пациента и APP_ENV не определяют права доступа.
    """
    patient = db.get(Patient, patient_id)
    return patient is not None and patient.deleted_at is None


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
        origin=_version(db, case).origin,
        versions_available=list(versions),
        approved_result=case.approved_result,
    )


def get_draft(db: Session, patient_id: str, doctor_id: str, request_id: str) -> DraftRead:
    _request(db, request_id, doctor_id, patient_id)
    return _read(db, _case(db, request_id))


def get_historical_version(
    db: Session, patient_id: str, doctor_id: str, request_id: str, version: int
) -> DraftRead:
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
        origin=row.origin,
        versions_available=list(all_versions),
    )


def import_draft(
    db: Session, patient_id: str, doctor_id: str, request_id: str, payload: DraftImport
) -> DraftRead:
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
        if _version(db, case).origin != "synthetic_manual_test":
            raise HTTPException(409, "AI-предложения меняются только через врачебный предпросмотр")
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


def _proposals_from_analysis(row: AIDemoAnalysis) -> list[Proposal]:
    """Без домысливания: v1 содержит обследования, гипотезы и лекарственные риски, но НЕ дозы."""
    source = DemoAnalysisSubmit.model_validate(row.payload_json)
    namespace = UUID(row.id)
    proposals: list[Proposal] = []
    for index, item in enumerate(source.suggested_examinations):
        order = OrderDraftCreate(
            request_key=uuid5(namespace, f"exam-order:{index}"),
            kind="examination",
            name=item.name,
            examination_details=item.rationale,
            indication="Оценка целесообразности обследования врачом",
            rationale=item.rationale,
            source_reference=f"AI-анализ {row.id}; {row.payload_sha256[:16]}",
        )
        proposals.append(
            Proposal(
                id=uuid5(namespace, f"exam:{index}"),
                kind="examination",
                order=order,
                evidence_status="unverified_ai",
                source_locator=f"suggested_examinations[{index}]",
            )
        )
    for index, item in enumerate(source.hypotheses):
        proposals.append(
            Proposal(
                id=uuid5(namespace, f"hypothesis:{index}"),
                kind="history_event",
                history=ManualHistoryCreate(
                    category="ai_diagnostic_hypothesis",
                    fact={
                        "title": item.title,
                        "rationale": item.rationale,
                        "confidence": item.confidence,
                        "classification": "предложение AI, не подтверждённый диагноз",
                    },
                ),
                evidence_status="unverified_ai",
                source_locator=f"hypotheses[{index}]",
            )
        )
    for index, item in enumerate(source.medication_risks):
        proposals.append(
            Proposal(
                id=uuid5(namespace, f"medication-risk:{index}"),
                kind="history_event",
                history=ManualHistoryCreate(
                    category="ai_medication_risk",
                    fact={
                        "medication": item.medication,
                        "risk": item.risk,
                        "severity": item.severity,
                        "classification": "сообщённый AI риск; требует проверки",
                    },
                ),
                evidence_status="unverified_ai",
                source_locator=f"medication_risks[{index}]",
            )
        )
    return proposals


def import_from_analysis(
    db: Session, patient_id: str, doctor_id: str, request_id: str
) -> DraftRead:
    """Конверсия неизменяемого ответа Site Builder в review; без назначения лечения."""
    request = _request(db, request_id, doctor_id, patient_id)
    analysis = db.scalar(
        select(AIDemoAnalysis).where(
            AIDemoAnalysis.request_id == request_id,
            AIDemoAnalysis.patient_id == patient_id,
            AIDemoAnalysis.doctor_id == doctor_id,
        )
    )
    if analysis is None:
        raise HTTPException(404, "Сохранённый AI-анализ ещё не получен")
    if (
        analysis.context_sha256 != request.context_sha256
        or analysis.orders_sha256 != request.review_orders_sha256
    ):
        raise HTTPException(409, "AI-анализ относится к другой версии запроса")
    # Если черновик уже создан, повторный вызов не переписывает врачебные решения.
    case = db.scalar(
        select(AIReviewCase).where(AIReviewCase.request_id == request_id).with_for_update()
    )
    if case is not None:
        version = _version(db, case)
        if version.origin != "site_builder_analysis_v1":
            raise HTTPException(409, "У запроса уже есть отдельный ручной черновик")
        events = db.scalars(
            select(AIReviewEvent).where(
                AIReviewEvent.case_id == case.id,
                AIReviewEvent.action == "imported_ai",
            )
        ).all()
        if not any(
            e.payload_json.get("analysis_id") == analysis.id
            and e.payload_json.get("payload_sha256") == analysis.payload_sha256
            for e in events
        ):
            raise HTTPException(409, "Источник предложений изменился")
        return _read(db, case)
    _fresh(db, request)
    proposals = _proposals_from_analysis(analysis)
    if not proposals:
        raise HTTPException(
            422,
            "В ответе нет структурируемых обследований, гипотез или рисков. "
            "Текст анализа сохранён без создания медицинских предложений.",
        )
    case = AIReviewCase(request_id=request_id, current_version=1, status="open")
    db.add(case)
    try:
        db.flush()
        db.add(
            AIReviewVersion(
                case_id=case.id,
                version=1,
                created_by_id=doctor_id,
                origin="site_builder_analysis_v1",
                proposals_json=[p.model_dump(mode="json") for p in proposals],
            )
        )
        _event(
            db,
            case,
            doctor_id,
            "imported_ai",
            {
                "analysis_id": analysis.id,
                "payload_sha256": analysis.payload_sha256,
                "proposal_count": len(proposals),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Предложения уже созданы другим запросом") from exc
    except Exception:
        db.rollback()
        raise
    return _read(db, case)


def import_structured_proposals(
    db: Session,
    patient_id: str,
    doctor_id: str,
    request_id: str,
    payload: StructuredProposalSubmit,
) -> DraftRead:
    """AI-предложения из того же MCP-агента, привязанные к уже сохранённому анализу.

    Источник данных проверяется, ID предложений и source_reference задаёт сервер.
    Повторный вызов с тем же JSON не создаёт новый черновик.
    """
    if str(payload.patient_id) != patient_id or str(payload.request_id) != request_id:
        raise HTTPException(409, "Несоответствие пациента или запроса")
    request = _request(db, request_id, doctor_id, patient_id)
    analysis = db.scalar(
        select(AIDemoAnalysis).where(
            AIDemoAnalysis.request_id == request_id,
            AIDemoAnalysis.patient_id == patient_id,
            AIDemoAnalysis.doctor_id == doctor_id,
        )
    )
    if analysis is None:
        raise HTTPException(409, "Сначала сохраните анализ через submit_demo_analysis")
    if any(
        (
            payload.context_sha256 != request.context_sha256,
            payload.orders_sha256 != request.review_orders_sha256,
            payload.analysis_payload_sha256 != analysis.payload_sha256,
        )
    ):
        raise HTTPException(409, "Указаны хеши другого анализа или контекста")
    _fresh(db, request)

    from hashlib import sha256

    canonical = payload.model_dump_json(exclude_none=False)
    digest = sha256(canonical.encode("utf-8")).hexdigest()

    case = db.scalar(
        select(AIReviewCase).where(AIReviewCase.request_id == request_id).with_for_update()
    )
    if case is not None:
        version = _version(db, case)
        if version.origin != "site_builder_structured_v1":
            raise HTTPException(409, "Для этого запроса уже имеется другой review")
        event = db.scalar(
            select(AIReviewEvent).where(
                AIReviewEvent.case_id == case.id,
                AIReviewEvent.action == "imported_ai",
            )
        )
        if event is None or event.payload_json.get("structured_payload_sha256") != digest:
            raise HTTPException(409, "Содержимое ранее полученного ответа отличается")
        return _read(db, case)

    # Агент не может назначить метку clinician_added или подменить ссылку на источник.
    proposals = []
    for i, item in enumerate(payload.proposals):
        order = item.order
        if order is not None:
            order = order.model_copy(
                update={
                    "source_reference": f"AI MCP {analysis.id} / {analysis.payload_sha256[:16]}",
                }
            )
        proposals.append(
            item.model_copy(
                update={
                    "id": uuid5(UUID(analysis.id), f"structured:{i}"),
                    "order": order,
                    "source_locator": f"structured_proposals[{i}]",
                    "evidence_status": "unverified_ai",
                }
            )
        )
    case = AIReviewCase(request_id=request_id, current_version=1, status="open")
    db.add(case)
    try:
        db.flush()
        db.add(
            AIReviewVersion(
                case_id=case.id,
                version=1,
                created_by_id=doctor_id,
                origin="site_builder_structured_v1",
                proposals_json=[p.model_dump(mode="json") for p in proposals],
            )
        )
        _event(
            db,
            case,
            doctor_id,
            "imported_ai",
            {
                "analysis_id": analysis.id,
                "payload_sha256": analysis.payload_sha256,
                "structured_payload_sha256": digest,
                "proposal_count": len(proposals),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Конкурентное создание структурированного черновика") from exc
    except Exception:
        db.rollback()
        raise
    return _read(db, case)


def add_clinician_order(
    db: Session,
    patient_id: str,
    doctor_id: str,
    request_id: str,
    payload: ClinicianOrderSupplement,
) -> DraftRead:
    """Добавление проверяемого врачебного назначения в связанные с AI версии."""
    request = _request(db, request_id, doctor_id, patient_id)
    case = _case(db, request_id, lock=True)
    if case.status != "open" or case.current_version != payload.expected_version:
        raise HTTPException(409, "Версия предложений изменилась")
    previous = _version(db, case)
    if previous.origin != "site_builder_analysis_v1":
        raise HTTPException(409, "Добавление доступно для сохранённого AI-анализа")
    _fresh(db, request)
    order = payload.order
    if order.kind != "medication":
        raise HTTPException(422, "Здесь допускается только врачебное лекарственное предложение")
    if not order.source_reference or not order.source_reference.strip():
        raise HTTPException(422, "Укажите источник назначения (например, клинический кейс)")
    proposed_order = ClinicalOrder(
        **order.model_dump(exclude={"request_key"}),
        request_key=str(order.request_key),
        patient_id=patient_id,
        author_id=doctor_id,
        status="draft",
        version=1,
    )
    _check_ready(proposed_order)
    existing = list(previous.proposals_json)
    if len(existing) >= 36:
        raise HTTPException(422, "Достигнуто максимальное число предложений")
    proposal = Proposal(
        id=uuid5(UUID(case.id), f"clinician:{case.current_version}:{order.request_key}"),
        kind="medication",
        order=order,
        evidence_status="clinician_added",
        source_locator="clinician_input",
    )
    if any(x["id"] == str(proposal.id) for x in existing):
        raise HTTPException(409, "Такое предложение уже добавлено")
    case.current_version += 1
    db.add(
        AIReviewVersion(
            case_id=case.id,
            version=case.current_version,
            created_by_id=doctor_id,
            origin=previous.origin,
            proposals_json=[*existing, proposal.model_dump(mode="json")],
        )
    )
    _event(
        db,
        case,
        doctor_id,
        "clinician_added",
        {
            "proposal_id": str(proposal.id),
            "source": "doctor_input",
            "source_reference": order.source_reference,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Версия уже создана параллельным запросом") from exc
    except Exception:
        db.rollback()
        raise
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
    version = _version(db, case)
    origin = getattr(version, "origin", "synthetic_manual_test")
    proposals = {item["id"]: item for item in version.proposals_json}
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
        kind = item["kind"]
        if kind == "demo_test":
            if any((entry.order, entry.history, entry.observation)) or (
                entry.test_id is not None and entry.test_id != item["test_id"]
            ):
                raise HTTPException(422, "Тест можно выбрать, но не заменить другим")
            definition(item["test_id"])
            data = {"test_id": item["test_id"], "test_version": definition(item["test_id"]).version}
            original = {"test_id": item["test_id"]}
            edited = False
            table = "questionnaire_assignments"
        elif kind in ("medication", "examination"):
            if any((entry.test_id, entry.history, entry.observation)):
                raise HTTPException(422, "Неверный тип редактирования")
            order = entry.order or OrderDraftCreate.model_validate(item["order"])
            if order.kind != kind:
                raise HTTPException(422, "Нельзя изменять вид назначения")
            original = item["order"]
            # Источник AI нельзя удалить или подменить редактированием полей.
            if origin in ("site_builder_analysis_v1", "site_builder_structured_v1"):
                order = order.model_copy(update={"source_reference": original["source_reference"]})
            data = order.model_dump(mode="json")
            data["request_key"] = str(uuid5(UUID(case.id), item["id"]))
            edited = any(data.get(k) != v for k, v in original.items() if k != "request_key")
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
        elif kind == "history_event":
            if any((entry.order, entry.test_id, entry.observation)):
                raise HTTPException(422, "Неверный тип редактирования истории")
            history = entry.history or ManualHistoryCreate.model_validate(item["history"])
            if origin == "site_builder_analysis_v1" and (
                history.category != item["history"]["category"]
                or history.encounter_id is not None
                or history.occurred_at is not None
                or history.fact.get("classification")
                != item["history"]["fact"].get("classification")
            ):
                raise HTTPException(422, "Категорию и дату AI-предложения нельзя менять")
            _encounter(
                db,
                request.patient_id,
                str(history.encounter_id) if history.encounter_id else None,
            )
            original = item["history"]
            data = history.model_dump(mode="json")
            edited = data != original
            table = "history_events"
        elif kind == "observation":
            if any((entry.order, entry.test_id, entry.history)):
                raise HTTPException(422, "Неверный тип редактирования наблюдения")
            observation = entry.observation or ManualObservationCreate.model_validate(
                item["observation"]
            )
            _encounter(
                db,
                request.patient_id,
                str(observation.encounter_id) if observation.encounter_id else None,
            )
            original = item["observation"]
            data = observation.model_dump(mode="json")
            edited = data != original
            table = "medical_observations"
        else:
            raise HTTPException(422, "Неизвестный тип предложения")
        changed |= edited
        selections.append(
            {
                "proposal_id": item["id"],
                "table": table,
                "original": original,
                "final": data,
                "edited": edited,
                "alternative_group": group,
                "source_locator": item.get("source_locator"),
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
        "not_selected": sorted(set(proposals) - {e["proposal_id"] for e in selections}),
        "edit_reason": payload.edit_reason if changed else None,
        "origin": origin,
    }
    body["preview_sha256"] = _sha(body)
    return body


def preview(
    db: Session, patient_id: str, doctor_id: str, request_id: str, payload: ReviewAction
) -> dict:
    request = _request(db, request_id, doctor_id, patient_id)
    return _prepare(db, _case(db, request_id), request, payload)


def approve(
    db: Session, patient_id: str, doctor_id: str, request_id: str, payload: ReviewCommit
) -> dict:
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
            elif item["table"] == "history_events":
                data = ManualHistoryCreate.model_validate(item["final"])
                row = HistoryEvent(
                    patient_id=patient_id,
                    encounter_id=str(data.encounter_id) if data.encounter_id else None,
                    category=data.category,
                    fact_json=data.fact,
                    occurred_at=data.occurred_at or utc_now(),
                    priority=data.priority,
                    source_ref=f"ai_review:{case.id}:{item['proposal_id']}",
                )
                db.add(row)
                db.flush()
                db.add(
                    ClinicalEntryAudit(
                        patient_id=patient_id,
                        actor_id=doctor_id,
                        record_type="history_event",
                        record_id=row.id,
                        action="ai_review_approved",
                        source_ref=row.source_ref,
                        details_json={
                            "request_id": request_id,
                            "proposal_id": item["proposal_id"],
                            "original": item["original"],
                            "final": item["final"],
                            "source_locator": item["source_locator"],
                            "edit_reason": summary["edit_reason"] if item["edited"] else None,
                        },
                    )
                )
            elif item["table"] == "medical_observations":
                data = ManualObservationCreate.model_validate(item["final"])
                row = MedicalObservation(
                    patient_id=patient_id,
                    encounter_id=str(data.encounter_id) if data.encounter_id else None,
                    code_system=data.code_system,
                    code=data.code,
                    value_json=data.value,
                    observed_at=data.observed_at or utc_now(),
                    source_ref=f"ai_review:{case.id}:{item['proposal_id']}",
                )
                db.add(row)
                db.flush()
                db.add(
                    ClinicalEntryAudit(
                        patient_id=patient_id,
                        actor_id=doctor_id,
                        record_type="medical_observation",
                        record_id=row.id,
                        action="ai_review_approved",
                        source_ref=row.source_ref,
                        details_json={
                            "request_id": request_id,
                            "proposal_id": item["proposal_id"],
                            "original": item["original"],
                            "final": item["final"],
                            "source_locator": item["source_locator"],
                            "edit_reason": summary["edit_reason"] if item["edited"] else None,
                        },
                    )
                )
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
                "not_selected": summary["not_selected"],
                "decisions": [
                    {
                        "proposal_id": x["proposal_id"],
                        "decision": "edited_and_accepted" if x["edited"] else "accepted",
                        "source_locator": x["source_locator"],
                    }
                    for x in summary["changes"]
                ]
                + [
                    {"proposal_id": proposal_id, "decision": "not_selected"}
                    for proposal_id in summary["not_selected"]
                ],
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
    _request(db, request_id, doctor_id, patient_id)
    case = _case(db, request_id, lock=True)
    if case.status != "open" or case.current_version != payload.expected_version:
        raise HTTPException(409, "Версия или статус изменились")
    case.status = "rejected"
    _event(db, case, doctor_id, "rejected", {"reason": payload.reason})
    db.commit()
    return _read(db, case)
