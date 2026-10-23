"""Версионированные СИНТЕТИЧЕСКИЕ опросники. Не PHQ-9 и не GAD-7."""

from dataclasses import dataclass

from app.clinical.scales import get_scale_definition

ANSWER_LABELS = (
    "Ни разу",
    "В отдельные дни",
    "Часто",
    "Почти ежедневно",
)


@dataclass(frozen=True)
class DemoTest:
    test_id: str
    version: str
    title: str
    description: str
    questions: tuple[str, ...]
    critical_index: int | None = None

    def to_catalog(self) -> dict:
        return {
            "test_id": self.test_id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "questions": list(self.questions),
            "answer_labels": list(ANSWER_LABELS),
            "demo_only": True,
            "source": "Синтетический учебный опросник AIDoctor; не валидирован",
            "interpretation": "Только сумма баллов и сравнение с прежними ответами. Не диагноз.",
            "critical_index": self.critical_index,
        }


CATALOG: dict[str, DemoTest] = {
    "DEMO_ANX_7": DemoTest(
        test_id="DEMO_ANX_7",
        version="demo-1",
        title="Учебный опросник тревожных переживаний (7 пунктов)",
        description="Самоотчёт за последние 14 дней; не клиническая шкала.",
        questions=(
            "Было трудно расслабиться после обычных дел?",
            "Беспокойство мешало сосредоточиться?",
            "Было трудно остановить повторяющиеся тревожные мысли?",
            "Отмечалось внутреннее напряжение?",
            "Беспокойство нарушало обычное расписание?",
            "Появлялось желание избегать привычных ситуаций из-за волнения?",
            "Тревожность мешала отдыху?",
        ),
    ),
    "DEMO_DEP_9": DemoTest(
        test_id="DEMO_DEP_9",
        version="demo-1",
        title="Учебный опросник самочувствия (9 пунктов)",
        description="Самоотчёт за последние 14 дней; не диагностика депрессии.",
        questions=(
            "Было сложно заинтересоваться привычными занятиями?",
            "Настроение ощущалось сниженным?",
            "Сон был менее восстанавливающим?",
            "Возникало чувство усталости?",
            "Менялся привычный аппетит?",
            "Было трудно оценивать свои успехи без самокритики?",
            "Было сложно удерживать внимание?",
            "Отмечалась необычная заторможенность или суетливость?",
            "Возникали мысли о причинении вреда себе?",
        ),
        critical_index=8,
    ),
}


def definition(test_id: str) -> DemoTest:
    if test_id not in CATALOG:
        raise ValueError("Неизвестный демонстрационный тест")
    item = CATALOG[test_id]
    scale = get_scale_definition(test_id)
    if scale.item_count != len(item.questions):
        raise RuntimeError("Каталог не соответствует подсчёту баллов")
    return item


def score(test_id: str, version: str, answers: list[int]) -> tuple[int, bool]:
    item = definition(test_id)
    if version != item.version:
        raise ValueError("Неподдерживаемая версия теста")
    result = get_scale_definition(test_id).calculate_score(answers)
    flagged = item.critical_index is not None and answers[item.critical_index] > 0
    return result, flagged
