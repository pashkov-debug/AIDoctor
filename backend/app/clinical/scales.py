from dataclasses import dataclass


class ScaleNotFoundError(ValueError):
    pass


class InvalidScaleResponseError(ValueError):
    pass


@dataclass(frozen=True)
class ScaleDefinition:
    scale_id: str
    item_count: int
    min_item_score: int
    max_item_score: int

    def calculate_score(
        self,
        item_scores: list[int],
    ) -> int:
        if len(item_scores) != self.item_count:
            raise InvalidScaleResponseError(
                f"{self.scale_id} expects {self.item_count} items, got {len(item_scores)}"
            )

        for index, score in enumerate(item_scores):
            if not (self.min_item_score <= score <= self.max_item_score):
                raise InvalidScaleResponseError(f"Item {index} has invalid score: {score}")

        return sum(item_scores)


SCALE_REGISTRY: dict[str, ScaleDefinition] = {
    "DEMO_DEP_9": ScaleDefinition(
        scale_id="DEMO_DEP_9",
        item_count=9,
        min_item_score=0,
        max_item_score=3,
    ),
    "DEMO_ANX_7": ScaleDefinition(
        scale_id="DEMO_ANX_7",
        item_count=7,
        min_item_score=0,
        max_item_score=3,
    ),
}


def get_scale_definition(
    scale_id: str,
) -> ScaleDefinition:
    definition = SCALE_REGISTRY.get(scale_id)

    if definition is None:
        raise ScaleNotFoundError(scale_id)

    return definition
