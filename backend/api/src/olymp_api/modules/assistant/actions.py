"""Кнопки под ответом: что можно открыть или сделать по найденному.

Собирает сервер из карточек, которые вернули инструменты и назвал ответ: клиент кнопки только
рисует. Ничего не придумываем: id берутся из результатов инструментов, как и у карточек.
"""

from typing import Any

MAX_ACTIONS = 4
SUGGEST_LABEL = "Предложить вуз или документ"


def first(entities: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((e for e in entities if e["kind"] == kind), None)


def build_actions(entities: list[dict[str, Any]], no_data: bool) -> list[dict[str, Any]]:
    """Кнопки по карточкам ответа (в порядке упоминания); no_data — поиск ничего не нашёл."""
    actions: list[dict[str, Any]] = []
    program = first(entities, "program")
    university = first(entities, "university")
    olympiad = first(entities, "olympiad")
    if program:
        actions.append(
            {"kind": "program", "label": f"Открыть направление: {program['label']}"}
            | {"program_id": program["id"]}
        )
    elif university:
        actions.append(
            {"kind": "university", "label": f"Открыть вуз: {university['label']}"}
            | {"university_id": university["id"]}
        )
    if olympiad:
        # профиль есть, только если ответ назвал его: без него олимпиада открывается целиком
        profile = {"profile_id": olympiad["profile_id"]} if "profile_id" in olympiad else {}
        base = {"olympiad_id": olympiad["id"], "name": olympiad["label"]} | profile
        actions.append(
            {"kind": "olympiad", "label": f"Открыть олимпиаду: {olympiad['label']}"} | base
        )
        actions.append(
            {"kind": "add_diploma", "label": f"Добавить диплом: {olympiad['label']}"} | base
        )
    if program:
        actions.append(
            {"kind": "goal", "label": "Подобрать олимпиады под цель"}
            | {"program_id": program["id"]}
        )
    actions = actions[:MAX_ACTIONS]
    if no_data:
        actions.append({"kind": "suggest", "label": SUGGEST_LABEL})
    return actions
