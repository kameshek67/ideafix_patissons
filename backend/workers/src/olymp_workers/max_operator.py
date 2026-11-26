"""Бот-оператор: жалобы «не совпадает с документом», сводка и состояние сервиса.

Дежурные из белого списка (OLYMP_MAX_OPERATOR_IDS — id пользователей MAX через запятую)
получают уведомление о каждой новой жалобе и команды:

    /reports            открытые жалобы, у каждой кнопки статусов
    /quote <№> <текст>  «данные верны» с цитатой из документа (без цитаты статус не ставится)
    /stats              за сутки: жалобы, «Поделиться»; чего нет в базе — «нет данных»
    /health             API, база, версия данных, включён ли помощник
    /operator           список команд

Автору жалобы из MAX бот пишет, когда статус сменился на «исправлено», «данные верны» или
«дубль»; автору ссылки из «Предложить вуз или документ» — когда оператор принял разбор.
Остальным пользователям бот отвечает как раньше (см. max_bot). База нужна только
этому режиму: без OLYMP_MAX_OPERATOR_IDS бот в неё не ходит.
"""

import json
import os
import urllib.request
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from typing import Any, TypeGuard

import psycopg
from olymp_db.session import database_url, psycopg_dsn
from psycopg.rows import dict_row

API_URL = "http://127.0.0.1:8000"
MAX_TEXT = 3800
REPORTS_PAGE = 10

OPEN_STATUSES = ["new", "seen", "checking"]
CLOSED_STATUSES = ["fixed", "correct", "duplicate"]
STATUS_TITLES = {
    "new": "новая",
    "seen": "выгружена",
    "checking": "проверяем",
    "fixed": "исправлено",
    "correct": "данные верны",
    "duplicate": "дубль",
}
REASON_TITLES = {
    "no_benefit": "льготы нет в документе",
    "wrong_type": "другой тип (БВИ или 100 баллов)",
    "winners_only": "только для победителей",
    "wrong_grade_or_level": "другой класс или уровень",
    "wrong_ege": "другой порог ЕГЭ",
    "broken_link": "ссылка не открывается",
    "other": "другое",
}
SOURCE_TITLES = {"user": "пользователь", "verifier": "сверщик", "monitor": "мониторинг"}
KIND_TITLES = {
    "program": "карточка направления",
    "olympiad": "выдача по олимпиаде",
    "benefit": "строка льготы",
}
HELP = (
    "Команды оператора:\n"
    "/reports — открытые жалобы с кнопками статусов\n"
    "/quote <№> <цитата> — «данные верны» с цитатой из документа\n"
    "/stats — сводка за сутки\n"
    "/health — API, база, версия данных, помощник"
)

# что бот отправляет и на что отвечает: ("send", user_id, тело) / ("answer", callback_id, тело)
Action = tuple[str, Any, dict[str, Any]]
Connect = Callable[[], psycopg.Connection[Any]]
FetchJson = Callable[[str], Any]


def operator_ids(raw: str | None) -> frozenset[int]:
    """«12, 34;56» -> {12, 34, 56}; нечисловое пропускаем."""
    ids = set()
    for part in (raw or "").replace(";", ",").split(","):
        if part.strip().isdigit():
            ids.add(int(part))
    return frozenset(ids)


def clip(text: str, limit: int = MAX_TEXT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def http_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 — адрес API из настроек
        return json.loads(response.read() or b"{}")


# ---------------------------------------------------------------- тексты


def report_text(report: dict[str, Any]) -> str:
    context = report["context"] or {}
    where = " · ".join(
        part
        for part in (context.get("university"), context.get("code"), context.get("program"))
        if part
    )
    lines = [
        f"Жалоба №{report['id']} · {STATUS_TITLES.get(report['status'], report['status'])} · "
        f"{SOURCE_TITLES.get(report['source'], report['source'])}, "
        f"{KIND_TITLES.get(report['kind'], report['kind'])}",
        where or "—",
    ]
    if context.get("olympiad"):
        conditions = " · ".join(
            str(part)
            for part in (
                context.get("benefit_type"),
                context.get("olympiad_profile") or context.get("olympiad_subject"),
                context.get("level"),
                context.get("winner_role"),
                context.get("grade"),
                context.get("min_ege") and f"ЕГЭ {context['min_ege']}",
            )
            if part
        )
        lines.append(
            f"Олимпиада: {context['olympiad']}" + (f" — {conditions}" if conditions else "")
        )
    if report["reason"]:
        lines.append(f"Причина: {REASON_TITLES.get(report['reason'], report['reason'])}")
    if report["message"]:
        lines.append(f"Сообщение: {report['message']}")
    if report["link"]:
        lines.append(f"Ссылка: {report['link']}")
    if context.get("source_url"):
        lines.append(f"Источник строки: {context['source_url']}")
    if report["quote"]:
        lines.append(f"Цитата из документа: «{report['quote']}»")
    return clip("\n".join(lines))


def report_keyboard(report_id: int) -> dict[str, Any]:
    def button(text: str, status: str) -> dict[str, Any]:
        return {"type": "callback", "text": text, "payload": f"r:{report_id}:{status}"}

    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [button("Проверяю", "checking"), button("Исправлено", "fixed")],
                [button("Данные верны", "correct"), button("Дубль", "duplicate")],
            ]
        },
    }


def report_body(report: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Карточка жалобы; у закрытой кнопок нет."""
    body: dict[str, Any] = {"text": prefix + report_text(report), "attachments": []}
    if report["status"] not in CLOSED_STATUSES:
        body["attachments"] = [report_keyboard(report["id"])]
    return body


def user_reply(report: dict[str, Any]) -> dict[str, Any]:
    """Короткий ответ автору жалобы после решения оператора."""
    context = report["context"] or {}
    what = ", ".join(part for part in (context.get("university"), context.get("olympiad")) if part)
    head = f"Ты писал про строку «{what}»." if what else "Ты писал нам про данные."
    status = report["status"]
    if status == "fixed":
        tail = "Проверили по документу и исправили. Спасибо, что заметил."
    elif status == "correct":
        quote = f" В документе: «{report['quote']}»." if report["quote"] else ""
        tail = (
            f"Проверили по документу: в таблице всё верно.{quote} "
            "Если не согласен, напиши ещё раз и приложи ссылку на документ."
        )
    else:
        tail = "Об этом уже сообщали, строку проверяем. Спасибо!"
    return {"text": clip(f"{head} {tail}")}


def stats_text(stats: dict[str, Any]) -> str:
    fix = (
        f", в среднем {float(stats['fix_hours']):.1f} ч до исправления"
        if stats["fix_hours"] is not None
        else ""
    )
    return "\n".join(
        [
            "За последние сутки",
            "Поиски: нет данных (запросы поиска нигде не записываются)",
            "Пустые выдачи: нет данных",
            f"Жалобы: новых {stats['created']}, закрыто {stats['closed']} "
            f"(исправлено {stats['fixed']}{fix}), открытых сейчас {stats['open']}",
            f"«Поделиться»: новых ссылок {stats['shares']}",
        ]
    )


def suggestion_reply(job: dict[str, Any]) -> dict[str, Any]:
    """Ответ автору ссылки из «Предложить вуз или документ» после принятия оператором."""
    return {"text": clip(f"Добавили документ вуза {job['university']}, спасибо.")}


# ---------------------------------------------------------------- работа с базой


class Reports:
    """Жалобы в базе: короткие соединения, чтобы обрыв связи не ломал долгий long polling."""

    def __init__(self, connect: Connect) -> None:
        self.connect = connect

    def one(self, report_id: int) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            return conn.execute("SELECT * FROM data_reports WHERE id = %s", (report_id,)).fetchone()

    def open(self, limit: int = REPORTS_PAGE) -> tuple[list[dict[str, Any]], int]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM data_reports WHERE status = ANY(%s) ORDER BY id LIMIT %s",
                (OPEN_STATUSES, limit),
            ).fetchall()
            total = conn.execute(
                "SELECT count(*) AS n FROM data_reports WHERE status = ANY(%s)", (OPEN_STATUSES,)
            ).fetchone()
        return rows, int(total["n"]) if total else len(rows)

    def set_status(
        self, report_id: int, status: str, quote: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        """Меняет статус. Возвращает (жалоба, ошибка): «данные верны» без цитаты не ставится."""
        if status not in {"checking", *CLOSED_STATUSES}:
            return None, "Такого статуса нет."
        quote = quote.strip()
        if status == "correct" and not quote:
            return None, "Для «данные верны» нужна цитата из документа."
        with closing(self.connect()) as conn:
            row = conn.execute(
                """UPDATE data_reports
                   SET status = %s,
                       quote = CASE WHEN %s <> '' THEN %s ELSE quote END,
                       resolved_at = CASE WHEN %s THEN now() ELSE NULL END
                   WHERE id = %s RETURNING *""",
                (status, quote, quote, status in CLOSED_STATUSES, report_id),
            ).fetchone()
            conn.commit()
        return (row, "") if row else (None, f"Жалобы №{report_id} нет.")

    def unannounced(self) -> list[dict[str, Any]]:
        """Новые жалобы, о которых операторам ещё не писали."""
        with closing(self.connect()) as conn:
            return conn.execute(
                """SELECT * FROM data_reports
                   WHERE operator_notified_at IS NULL AND status = 'new' ORDER BY id LIMIT 20"""
            ).fetchall()

    def mark_announced(self, report_id: int) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                "UPDATE data_reports SET operator_notified_at = now() WHERE id = %s", (report_id,)
            )
            conn.commit()

    def unanswered(self) -> list[dict[str, Any]]:
        """Решённые жалобы из MAX, автору которых ещё не ответили на этот статус."""
        with closing(self.connect()) as conn:
            return conn.execute(
                """SELECT * FROM data_reports
                   WHERE max_user_id IS NOT NULL AND status = ANY(%s)
                         AND user_notified_status <> status ORDER BY id LIMIT 20""",
                (CLOSED_STATUSES,),
            ).fetchall()

    def mark_answered(self, report_id: int, status: str) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                "UPDATE data_reports SET user_notified_status = %s WHERE id = %s",
                (status, report_id),
            )
            conn.commit()

    def accepted_suggestions(self) -> list[dict[str, Any]]:
        """Принятые задачи из «Предложить вуз или документ», автору из MAX ещё не ответили."""
        with closing(self.connect()) as conn:
            return conn.execute(
                """SELECT j.id, j.max_user_id, s.university FROM source_jobs j
                   JOIN sources s ON s.id = j.source_id
                   WHERE j.origin = 'user' AND j.status = 'accepted' AND j.max_user_id IS NOT NULL
                         AND j.user_notified_at IS NULL ORDER BY j.id LIMIT 20"""
            ).fetchall()

    def mark_suggestion_answered(self, job_id: int) -> None:
        with closing(self.connect()) as conn:
            conn.execute("UPDATE source_jobs SET user_notified_at = now() WHERE id = %s", (job_id,))
            conn.commit()

    def stats(self) -> dict[str, Any]:
        """Числа за последние сутки из того, что реально лежит в базе."""
        with closing(self.connect()) as conn:
            one = conn.execute(
                """SELECT
                     count(*) FILTER (WHERE created_at >= now() - interval '1 day') AS created,
                     count(*) FILTER (WHERE resolved_at >= now() - interval '1 day') AS closed,
                     count(*) FILTER (WHERE resolved_at >= now() - interval '1 day'
                                      AND status = 'fixed') AS fixed,
                     avg(extract(epoch FROM resolved_at - created_at) / 3600)
                       FILTER (WHERE resolved_at >= now() - interval '1 day'
                               AND status = 'fixed') AS fix_hours,
                     count(*) FILTER (WHERE status = ANY(%s)) AS open
                   FROM data_reports""",
                (OPEN_STATUSES,),
            ).fetchone()
            shares = conn.execute(
                "SELECT count(*) AS n FROM share_links WHERE created_at >= now() - interval '1 day'"
            ).fetchone()
        assert one is not None and shares is not None
        return {**one, "shares": shares["n"]}

    def data_version(self) -> str | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
        return str(row["value"]) if row else None


# ---------------------------------------------------------------- оператор


@dataclass
class Operator:
    ids: frozenset[int]
    reports: Reports
    api_url: str = API_URL
    fetch_json: FetchJson = http_json

    def is_operator(self, user_id: object) -> TypeGuard[int]:
        return isinstance(user_id, int) and user_id in self.ids

    # --- команды и кнопки

    def handle_update(self, update: dict[str, Any]) -> list[Action] | None:
        """Действия на событие оператора; None — не наше событие, бот отвечает как обычно."""
        kind = update.get("update_type")
        if kind == "message_callback":
            callback = update.get("callback") or {}
            user = (callback.get("user") or {}).get("user_id")
            payload = str(callback.get("payload") or "")
            if not self.is_operator(user) or not payload.startswith("r:"):
                return None
            return self.on_button(user, str(callback.get("callback_id") or ""), payload)
        if kind == "message_created":
            message = update.get("message") or {}
            sender = message.get("sender") or {}
            recipient = message.get("recipient") or {}
            text = ((message.get("body") or {}).get("text") or "").strip()
            if (
                not self.is_operator(sender.get("user_id"))
                or sender.get("is_bot")
                or recipient.get("chat_type") != "dialog"
                or not text.startswith("/")
            ):
                return None
            return self.on_command(sender["user_id"], text)
        return None

    def on_command(self, user_id: int, text: str) -> list[Action] | None:
        command, _, rest = text.partition(" ")
        match command.lower():
            case "/reports":
                return self.list_reports(user_id)
            case "/stats":
                return [("send", user_id, {"text": stats_text(self.reports.stats())})]
            case "/health":
                return [("send", user_id, {"text": self.health()})]
            case "/operator":
                return [("send", user_id, {"text": HELP})]
            case "/quote":
                number, _, quote = rest.strip().partition(" ")
                if not number.isdigit():
                    return [("send", user_id, {"text": "Формат: /quote <номер жалобы> <цитата>"})]
                report, error = self.reports.set_status(int(number), "correct", quote)
                body = report_body(report) if report else {"text": error}
                return [("send", user_id, body)]
        return None

    def list_reports(self, user_id: int) -> list[Action]:
        rows, total = self.reports.open()
        if not rows:
            return [("send", user_id, {"text": "Открытых жалоб нет."})]
        shown = f", показаны первые {len(rows)}" if total > len(rows) else ""
        head: Action = ("send", user_id, {"text": f"Открытых жалоб: {total}{shown}"})
        return [head, *(("send", user_id, report_body(row)) for row in rows)]

    def on_button(self, user_id: int, callback_id: str, payload: str) -> list[Action]:
        parts = payload.split(":")
        if len(parts) != 3 or not parts[1].isdigit():
            return [("answer", callback_id, {"notification": "Не понял кнопку"})]
        number, status = int(parts[1]), parts[2]
        if status == "correct":
            # кнопка не несёт текст, цитату оператор присылает командой
            if self.reports.one(number) is None:
                return [("answer", callback_id, {"notification": f"Жалобы №{number} нет"})]
            ask = f"Пришли цитату из документа одной командой:\n/quote {number} <текст цитаты>"
            return [
                ("answer", callback_id, {"notification": "Нужна цитата из документа"}),
                ("send", user_id, {"text": ask}),
            ]
        report, error = self.reports.set_status(number, status)
        if report is None:
            return [("answer", callback_id, {"notification": error})]
        return [("answer", callback_id, {"message": report_body(report)})]

    # --- уведомления

    def outbox(self) -> list[tuple[list[Action], Callable[[], None]]]:
        """Что разослать по базе: (действия, отметка «сделано» — после успешной отправки)."""
        out: list[tuple[list[Action], Callable[[], None]]] = []
        for report in self.reports.unannounced():
            body = report_body(report, "Новая жалоба\n")
            actions: list[Action] = [("send", op, body) for op in sorted(self.ids)]
            out.append((actions, self.announced(report["id"])))
        for report in self.reports.unanswered():
            action: Action = ("send", report["max_user_id"], user_reply(report))
            out.append(([action], self.answered(report["id"], report["status"])))
        for job in self.reports.accepted_suggestions():
            reply: Action = ("send", job["max_user_id"], suggestion_reply(job))
            out.append(([reply], self.suggestion_answered(job["id"])))
        return out

    def suggestion_answered(self, job_id: int) -> Callable[[], None]:
        return lambda: self.reports.mark_suggestion_answered(job_id)

    def announced(self, report_id: int) -> Callable[[], None]:
        return lambda: self.reports.mark_announced(report_id)

    def answered(self, report_id: int, status: str) -> Callable[[], None]:
        return lambda: self.reports.mark_answered(report_id, status)

    # --- здоровье

    def health(self) -> str:
        def probe(path: str) -> Any:
            try:
                return self.fetch_json(self.api_url.rstrip("/") + path)
            except Exception:  # noqa: BLE001 — любая причина значит «не отвечает»
                return None

        api = probe("/readyz") is not None
        assistant = probe("/v1/assistant/config")
        try:
            version = self.reports.data_version()
            database = "ок" if version else "ок, но данные не собраны"
        except Exception:  # noqa: BLE001
            version, database = None, "не отвечает"
        if assistant is None:
            helper = "неизвестно, API не отвечает"
        else:
            helper = "включён" if assistant.get("enabled") else "выключен"
        return "\n".join(
            [
                f"API: {'ок' if api else 'не отвечает'}",
                f"База: {database}",
                f"Версия данных: {version or 'нет данных'}",
                f"Помощник: {helper}",
            ]
        )


def from_env() -> Operator | None:
    """Оператор из переменных окружения; без списка id режим выключен."""
    ids = operator_ids(os.environ.get("OLYMP_MAX_OPERATOR_IDS"))
    if not ids:
        return None
    dsn = psycopg_dsn(database_url())
    return Operator(
        ids=ids,
        reports=Reports(lambda: psycopg.connect(dsn, row_factory=dict_row)),
        api_url=os.environ.get("OLYMP_API_URL", "").strip() or API_URL,
    )
