"""Графики к анализу данных (docs/img) по готовому data/analysis/results.json.

Нужен matplotlib: `uv run --project backend --with matplotlib olymp-analysis --charts-only`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

BLUE = "#3b6ea8"
ORANGE = "#d9822b"
GREEN = "#4c9a6a"
GRAY = "#b9bec6"
INK = "#2b2f36"
DPI = 150

plt.rcParams.update(
    {
        "font.size": 10,
        "axes.edgecolor": GRAY,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "figure.facecolor": "white",
    }
)


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%".replace(".", ",")


def shorten(text: str, limit: int = 34) -> str:
    text = text.replace("«", "").replace("»", "").rstrip("…")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def hbars(
    ax: Axes, labels: list[str], values: list[float], color: str, *, fmt: Callable[[float], str]
) -> None:
    """Горизонтальные столбики, самый большой сверху, значения справа."""
    ypos = list(range(len(labels)))[::-1]
    ax.barh(ypos, values, color=color, height=0.68)
    ax.set_yticks(ypos, labels)
    top = max(values) if values else 1
    for y, v in zip(ypos, values, strict=True):
        ax.text(v + top * 0.015, y, fmt(v), va="center", fontsize=9)
    ax.set_xlim(0, top * 1.18)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_visible(False)
    ax.spines["bottom"].set_visible(False)


def save(fig: Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def prize_2027(data: dict[str, Any], out: Path) -> Path:
    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"wspace": 0.75})
    unis = data["top_universities"]
    ypos = list(range(len(unis)))[::-1]
    left.barh(
        ypos,
        [u["prize_programs"] for u in unis],
        color=GRAY,
        height=0.68,
        label="БВИ доступно призёрам",
    )
    left.barh(
        ypos, [u["programs"] for u in unis], color=ORANGE, height=0.68, label="станет 100 баллами"
    )
    left.set_yticks(ypos, [shorten(u["name"], 30) for u in unis])
    for y, u in zip(ypos, unis, strict=True):
        left.text(
            u["prize_programs"] + 2,
            y,
            f"{u['programs']} из {u['prize_programs']}",
            va="center",
            fontsize=9,
        )
    left.set_title("Вузы: направления, где БВИ призёра заменят на 100 баллов")
    left.legend(frameon=False, loc="lower right", fontsize=9)
    left.set_xlim(0, max(u["prize_programs"] for u in unis) * 1.3)
    left.tick_params(axis="y", length=0)
    left.xaxis.set_visible(False)
    left.spines["bottom"].set_visible(False)

    olymps = data["top_olympiads"]
    hbars(
        right,
        [shorten(o["name"], 30) for o in olymps],
        [o["programs"] for o in olymps],
        ORANGE,
        fmt=lambda v: f"{v:.0f}",
    )
    right.set_title("Олимпиады: направления с заменой")
    return save(fig, out)


def old_table(data: dict[str, Any], out: Path) -> Path:
    order = ["missing", "extra", "detail", "role", "ege", "grade_level"]
    titles = data["types"]
    sets = [
        ("development", "Страницы, на которых настраивали", BLUE),
        ("holdout", "Отложенные страницы", ORANGE),
    ]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    height = 0.38
    ypos = list(range(len(order)))[::-1]
    for i, (key, label, color) in enumerate(sets):
        entry = data["sets"][key]
        values = [entry["shares"][t] or 0 for t in order]
        pos = [y + (0.2 if i == 0 else -0.2) for y in ypos]
        ax.barh(
            pos,
            [v * 100 for v in values],
            height=height,
            color=color,
            label=f"{label} (расхождений: {entry['problems']})",
        )
        for y, v, t in zip(pos, values, order, strict=True):
            ax.text(v * 100 + 1, y, f"{pct(v)} · {entry['counts'][t]}", va="center", fontsize=8.5)
    ax.set_yticks(ypos, [titles[t] for t in order])
    ax.set_xlim(0, 112)
    ax.set_xlabel("доля от расхождений набора, %")
    ax.tick_params(axis="y", length=0)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.set_title("Чем строки старой таблицы отличаются от документов вузов")
    return save(fig, out)


def list_change(data: dict[str, Any], out: Path) -> Path:
    top = data["top"]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    hbars(
        ax,
        [f"{shorten(t['name'], 36)}  ({t['universities']} вуз.)" for t in top],
        [t["bvi_programs"] for t in top],
        BLUE,
        fmt=lambda v: f"{v:.0f}",
    )
    ax.set_title("Олимпиады вне перечня 2026/27: направления с БВИ по ним")
    return save(fig, out)


def concentration_pairs(data: dict[str, Any], out: Path) -> Path:
    fig, (left, right) = plt.subplots(1, 2, figsize=(13, 5.8), gridspec_kw={"wspace": 1.05})
    for ax, role, title, color in (
        (left, "winners", "Победителям", BLUE),
        (right, "prizes", "Призёрам", ORANGE),
    ):
        top = data[role]["top"]
        labels = [f"{shorten(t['olympiad'], 22)} — {shorten(t['profile'], 20)}" for t in top]
        hbars(ax, labels, [t["programs"] for t in top], color, fmt=lambda v: f"{v:.0f}")
        ax.set_title(f"{title}: направления с БВИ")
    return save(fig, out)


def concentration_cumulative(data: dict[str, Any], out: Path) -> Path:
    cum = data["cumulative"]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    xs = list(range(1, len(cum) + 1))
    ax.plot(xs, [c * 100 for c in cum], color=BLUE, lw=2)
    ax.plot(xs, [x / data["olympiads_with_bvi"] * 100 for x in xs], color=GRAY, lw=1.5, ls="--")
    for n in (10, data["olympiads_for_50"]):
        if n and n <= len(cum):
            ax.scatter([n], [cum[n - 1] * 100], color=ORANGE, zorder=3)
            ax.annotate(
                f"{n} олимпиад — {pct(cum[n - 1])}",
                (n, cum[n - 1] * 100),
                (n - 8, cum[n - 1] * 100 + 6),
                fontsize=9,
            )
    ax.set_xlabel("число олимпиад, начиная с самых частых")
    ax.set_ylabel("доля связей «направление — олимпиада», %")
    ax.set_ylim(0, 100)
    ax.text(
        len(cum) * 0.55,
        100 * len(cum) * 0.55 / data["olympiads_with_bvi"] - 6,
        "если бы льготы делились поровну",
        color="#6b7280",
        fontsize=8.5,
    )
    ax.set_title("Льготы распределены широко, а не по трём-четырём олимпиадам")
    return save(fig, out)


def ai_extraction(data: dict[str, Any], out: Path) -> Path:
    ex = data["extraction"]
    groups = [
        ("Страницы разработки", ex["dev_table"], ex["dev_extract"]),
        ("Отложенные страницы", ex["holdout_table"], ex["holdout_extract"]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), sharey=True)
    for ax, (title, table, extract) in zip(axes, groups, strict=True):
        names = ["точность", "полнота"]
        xs = [0, 1]
        w = 0.36
        t_vals = [table["precision"] * 100, table["recall"] * 100]
        e_vals = [extract["precision"] * 100, extract["recall"] * 100]
        ax.bar([x - w / 2 for x in xs], t_vals, w, color=GRAY, label="старая таблица")
        ax.bar([x + w / 2 for x in xs], e_vals, w, color=BLUE, label="извлечение из документов")
        for x, v in zip([x - w / 2 for x in xs], t_vals, strict=True):
            ax.text(x, v + 1.5, f"{v:.1f}".replace(".", ",") + "%", ha="center", fontsize=9)
        for x, v in zip([x + w / 2 for x in xs], e_vals, strict=True):
            ax.text(x, v + 1.5, f"{v:.1f}".replace(".", ",") + "%", ha="center", fontsize=9)
        ax.set_xticks(xs, names)
        ax.set_ylim(0, 125)
        ax.set_title(f"{title}: {extract['gold']} записей эталона")
    axes[0].set_ylabel("%")
    axes[0].legend(frameon=False, loc="upper left", fontsize=9)
    fig.suptitle(
        "Извлечение льгот из документов против эталона",
        x=0.07,
        ha="left",
        fontweight="bold",
        fontsize=12,
    )
    return save(fig, out)


MODEL_NAMES = {
    "deepseek-flash": "DeepSeek flash",
    "deepseek-v4-pro": "DeepSeek v4 pro",
    "deepseek/deepseek-v4-pro-0813": "DeepSeek v4 pro 0813",
    "google/gemini-3.1-flash-lite": "Gemini 3.1 flash-lite",
    "z-ai/glm-5.3": "GLM 5.3",
    "openai/gpt-6-luna": "GPT-6 luna",
    "qwen/qwen3.7-flash": "Qwen 3.7 flash",
}


def ai_assistant(data: dict[str, Any], out: Path) -> Path:
    models = data["assistant"]["models"]
    base = str(data["assistant"]["base_messages"])
    full = [m for m in models if m["cases"] >= 60]
    fig, (a, b, c) = plt.subplots(1, 3, figsize=(14, 4.4), gridspec_kw={"wspace": 0.45})
    names = [MODEL_NAMES.get(m["model"], m["model"]) for m in full]
    xs = list(range(len(full)))
    w = 0.36
    a.bar(
        [x - w / 2 for x in xs],
        [m["error_share_raw"] * 100 for m in full],
        w,
        color=ORANGE,
        label="до проверки кодом",
    )
    a.bar(
        [x + w / 2 for x in xs],
        [m["error_share_final"] * 100 for m in full],
        w,
        color=GREEN,
        label="после проверки",
    )
    for x, m in zip(xs, full, strict=True):
        a.text(
            x - w / 2,
            m["error_share_raw"] * 100 + 0.4,
            f"{m['error_share_raw'] * 100:.0f}%",
            ha="center",
            fontsize=9,
        )
        a.text(
            x + w / 2,
            m["error_share_final"] * 100 + 0.4,
            f"{m['error_share_final'] * 100:.0f}%",
            ha="center",
            fontsize=9,
        )
    a.set_xticks(xs, names)
    a.set_ylim(0, 20)
    a.set_title("Ответы с ошибкой факта, %")
    a.legend(frameon=False, fontsize=9)

    b.bar(xs, [m["answer_p95"] for m in full], 0.5, color=BLUE)
    b.axhline(20, color=ORANGE, ls="--", lw=1.3)
    b.text(len(full) - 0.55, 20.8, "порог 20 с", ha="right", color=ORANGE, fontsize=9)
    for x, m in zip(xs, full, strict=True):
        b.text(x, m["answer_p95"] + 0.8, f"{m['answer_p95']:.0f} с", ha="center", fontsize=9)
    b.set_xticks(xs, names)
    b.set_ylim(0, 52)
    b.set_title("Время ответа, p95")

    c.bar(xs, [m["cost_per_student_year"][base] * 100 for m in full], 0.5, color=BLUE)
    for x, m in zip(xs, full, strict=True):
        c.text(
            x,
            m["cost_per_student_year"][base] * 100 + 0.5,
            f"{m['cost_per_student_year'][base] * 100:.1f}".replace(".", ",") + " ¢",
            ha="center",
            fontsize=9,
        )
    c.set_xticks(xs, names)
    c.set_title(f"Цена на школьника в год ({base} сообщений), центы")
    for ax in (a, b, c):
        ax.tick_params(axis="x", labelsize=9)
    fig.suptitle(
        "Помощник: модели на полном наборе из 69 вопросов",
        x=0.07,
        ha="left",
        fontweight="bold",
        fontsize=12,
        y=1.02,
    )
    return save(fig, out)


def spaced(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def monitoring_dynamics(data: dict[str, Any], out: Path) -> Path:
    rows = data["dynamics"]["by_year"]
    years = [str(r["year"]) for r in rows]
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    bars = ax.bar(years, [r["total"] for r in rows], color=BLUE, width=0.62)
    for bar, r in zip(bars, rows, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            r["total"] + 120,
            spaced(r["total"]),
            ha="center",
            fontsize=9,
        )
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            300,
            f"{r['with_olympiads']}",
            ha="center",
            color="white",
            fontsize=10,
            fontweight="bold",
        )
    ax.set_ylim(0, max(r["total"] for r in rows) * 1.14)
    ax.set_ylabel("принято победителей и призёров олимпиад, чел.")
    ax.set_xlabel("год приёма (в основании столбца — число вузов с олимпиадниками, больше нуля)")
    first, last = rows[0], rows[-1]
    ax.set_title(
        f"Олимпиадников принимают на {data['dynamics']['growth_total_pct']:.0f}% больше, чем в "
        f"{first['year']}: {spaced(first['total'])} → {spaced(last['total'])}".replace(".", ",")
    )
    return save(fig, out)


def monitoring_concentration(data: dict[str, Any], out: Path) -> Path:
    conc = data["concentration"]
    fig, (left, mid, right) = plt.subplots(
        1, 3, figsize=(14, 4.6), gridspec_kw={"width_ratios": [1, 1, 1.15], "wspace": 0.55}
    )
    for year, color in ((str(data["years"][0]), GRAY), (str(conc["year"]), BLUE)):
        pts = conc["lorenz"][year]
        gini = next(r["gini_positive"] for r in conc["by_year"] if str(r["year"]) == year)
        left.plot(
            [p[0] * 100 for p in pts],
            [p[1] * 100 for p in pts],
            color=color,
            lw=2,
            label=f"{year}, Джини {gini:.2f}".replace(".", ","),
        )
    left.plot([0, 100], [0, 100], color=GRAY, lw=1, ls="--")
    left.set_xlabel("вузы с олимпиадниками, % (от меньших к большим)")
    left.set_ylabel("доля принятых олимпиадников, %")
    left.legend(frameon=False, fontsize=9, loc="upper left")
    top = next(r for r in conc["by_year"] if r["year"] == conc["year"])
    left.set_title(f"Топ-10 вузов принимают {pct(top['top10_share'])}")

    def paired(ax: Axes, items: list[dict[str, Any]], title: str) -> None:
        ypos = list(range(len(items)))[::-1]
        ax.barh([y + 0.19 for y in ypos], [i["share"] * 100 for i in items], 0.36, color=ORANGE)
        ax.barh(
            [y - 0.19 for y in ypos], [i["students_share"] * 100 for i in items], 0.36, color=GRAY
        )
        ax.set_yticks(ypos, [i["name"] for i in items])
        for y, i in zip(ypos, items, strict=True):
            ax.text(i["share"] * 100 + 1, y + 0.19, pct(i["share"]), va="center", fontsize=8.5)
            ax.text(
                i["students_share"] * 100 + 1,
                y - 0.19,
                pct(i["students_share"]),
                va="center",
                fontsize=8.5,
                color="#6b7280",
            )
        ax.set_xlim(0, 100)
        ax.tick_params(axis="y", length=0)
        ax.xaxis.set_visible(False)
        ax.spines["bottom"].set_visible(False)
        ax.set_title(title)

    paired(mid, conc["region_groups"], "Москва, Петербург, регионы")
    paired(right, conc["fed_districts"], "Федеральные округа")
    mid.legend(
        handles=[
            plt.Rectangle((0, 0), 1, 1, color=ORANGE),
            plt.Rectangle((0, 0), 1, 1, color=GRAY),
        ],
        labels=["доля олимпиадников", "доля студентов"],
        frameon=False,
        fontsize=8.5,
        loc="center right",
    )
    return save(fig, out)


def monitoring_score(data: dict[str, Any], out: Path) -> Path:
    link = data["score_link"]
    fig, (left, right) = plt.subplots(
        1, 2, figsize=(12.5, 4.8), gridspec_kw={"width_ratios": [1.1, 1], "wspace": 0.95}
    )
    left.scatter(
        [p["score"] for p in link["points"]],
        [p["percent"] for p in link["points"]],
        s=18,
        color=BLUE,
        alpha=0.65,
    )
    left.set_yscale("log")
    left.set_xlabel("средний балл ЕГЭ принятых на бюджет")
    left.set_ylabel("доля олимпиадников, % (лог. шкала)")
    r = link["last_year"]
    left.set_title(f"{link['year']}: Спирмен {r['rho']:.2f}, вузов {r['n']}".replace(".", ","))
    profiles = sorted(link["by_profile"], key=lambda p: -p["rho"])
    ypos = list(range(len(profiles)))[::-1]
    right.barh(
        ypos,
        [p["rho"] for p in profiles],
        color=[GREEN if p["rho"] > 0.4 else GRAY for p in profiles],
    )
    right.set_yticks(ypos, [f"{shorten(p['profile'], 26)} ({p['n']})" for p in profiles])
    for y, p in zip(ypos, profiles, strict=True):
        right.text(
            max(p["rho"], 0) + 0.02, y, f"{p['rho']:.2f}".replace(".", ","), va="center", fontsize=9
        )
    right.set_xlim(0, 1)
    right.tick_params(axis="y", length=0)
    right.set_xlabel("Спирмен, среднее по годам с данными (в скобках — число вузов)")
    right.set_title("По профилю вуза")
    return save(fig, out)


def draw_all(results: dict[str, Any], img_dir: Path) -> list[Path]:
    paths = [
        prize_2027(results["prize_2027"], img_dir / "prize-2027.png"),
        old_table(results["old_table"], img_dir / "old-table-diffs.png"),
        list_change(results["list_2026_27"], img_dir / "list-2026-27.png"),
        concentration_pairs(results["concentration"], img_dir / "concentration-pairs.png"),
        concentration_cumulative(
            results["concentration"], img_dir / "concentration-cumulative.png"
        ),
        ai_extraction(results["ai"], img_dir / "ai-extraction.png"),
        ai_assistant(results["ai"], img_dir / "ai-assistant.png"),
    ]
    if "monitoring" in results:
        m = results["monitoring"]
        paths += [
            monitoring_dynamics(m, img_dir / "monitoring-dynamics.png"),
            monitoring_concentration(m, img_dir / "monitoring-concentration.png"),
            monitoring_score(m, img_dir / "monitoring-score.png"),
        ]
    return paths
