"""Детерминированный учебный контроль режима Авиандр при ГТР.

Это НЕ система оценки вероятности передозировки и не клинический справочник.
Нельзя автоматически изменять назначения по результату правила.
"""

from decimal import Decimal

REGISTRY_REFERENCE = "https://www.rlsnet.ru/drugs/aviandr-89501"
EXPECTED_DOSE_MG = Decimal("20")
EXPECTED_FREQUENCY = 2


def check_order_regimen(
    *,
    name: str | None,
    active_ingredient: str | None,
    dose_value: Decimal | int | str | None,
    dose_unit: str | None,
    frequency_per_day: int | None,
) -> dict | None:
    names = f"{name or ''} {active_ingredient or ''}".casefold()
    if not any(x in names for x in ("авиандр", "маритупирдин", "aviandr", "maritupirdine")):
        return None
    if dose_value is None or frequency_per_day is None or not dose_unit:
        return None

    # При несовпадении единиц не пытаемся конвертировать произвольные дозировки.
    unit = dose_unit.lower().strip()
    if unit not in ("мг", "mg"):
        return {
            "severity": "warning",
            "rule_id": "aviandr_regimen_units_v1",
            "message": "Невозможно сверить дозу: единица измерения не распознана.",
            "basis": "Нужна проверка врачом по действующей инструкции РФ.",
            "source": REGISTRY_REFERENCE,
        }
    dose = Decimal(str(dose_value))
    daily = dose * frequency_per_day
    expected_daily = EXPECTED_DOSE_MG * EXPECTED_FREQUENCY
    if dose == EXPECTED_DOSE_MG and frequency_per_day == EXPECTED_FREQUENCY:
        return None
    return {
        "severity": "high" if daily > expected_daily else "warning",
        "rule_id": "aviandr_gad_regimen_v1",
        "message": (
            f"Назначение {dose:g} мг × {frequency_per_day}/сут "
            f"({daily:g} мг/сут) отличается от режима инструкции "
            "для ГТР: 20 мг два раза в сутки (40 мг/сут)."
        ),
        "basis": (
            "Возможно повышение риска нежелательных реакций, в том числе "
            "сонливости, головокружения и нарушения внимания. "
            "Конкретные последствия для данного пациента не предсказываются. "
            "Требуется проверка врачом; изменение/отмена не выполняются автоматически."
        ),
        "source": REGISTRY_REFERENCE,
    }
