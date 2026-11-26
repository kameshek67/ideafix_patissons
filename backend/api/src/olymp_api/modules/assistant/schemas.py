from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from olymp_api.schemas import ResponseModel

from .context import MAX_TOKEN_CHARS

MAX_MESSAGES = 20
MAX_MESSAGE_CHARS = 2000
MAX_HISTORY_CHARS = 16_000


class ChatMessage(BaseModel):
    # роли system и tool с клиента запрещены: иначе можно подделать «факты» и правила
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    diplomas: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Строки дипломов, если ученик разрешил их учитывать",
    )
    context: str | None = Field(
        default=None,
        max_length=MAX_TOKEN_CHARS,
        description="Контекст диалога из события done прошлого ответа, как есть. Подписан "
        "сервером: изменённый или устаревший контекст молча не учитывается",
    )

    @model_validator(mode="after")
    def check_history(self) -> Self:
        if self.messages[-1].role != "user":
            raise ValueError("последнее сообщение должно быть от ученика")
        if sum(len(m.content) for m in self.messages) > MAX_HISTORY_CHARS:
            raise ValueError("история слишком длинная")
        return self


class FeedbackRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=64)
    rating: Literal[1, -1]


class AssistantConfig(ResponseModel):
    enabled: bool
    model_label: str | None
    suggestions: list[str]


class AssistantEntity(ResponseModel):
    """Карточка в ответе: открывает экран приложения."""

    kind: Literal["olympiad", "program", "university"]
    id: int
    label: str
    hint: str | None = None


class AssistantSource(ResponseModel):
    url: str
    title: str


class AssistantStreamEvent(ResponseModel):
    """Данные одного события потока. Какие поля заполнены, зависит от типа события (event:)."""

    text: str | None = Field(
        default=None,
        description="status — что делает помощник; delta — кусок ответа; notice — оговорка "
        "под ответом (показывать отдельно, в историю не отправлять)",
    )
    entities: list[AssistantEntity] | None = None
    sources: list[AssistantSource] | None = None
    message_id: str | None = None
    context: str | None = Field(
        default=None,
        description="done — подписанный контекст диалога (id найденного и сводка фактов): "
        "хранить и прислать в следующем запросе в поле context",
    )
    code: str | None = None
