# -*- coding: utf-8 -*-
"""
Заполнение шаблона презентации хакатона под проект «Олимп».

    python build_deck.py

Берёт официальный шаблон, подставляет тексты проекта и сохраняет готовый файл.
Формат шаблона не ломаем: правим текст внутри существующих run'ов и копируем
абзацы через deepcopy, чтобы сохранить шрифты, цвета и отступы.

Абзац описывается списком кусков (текст, жирный) — так подзаголовок и пояснение
живут в одном абзаце и не съедают вертикальное место отбивками.
"""

from __future__ import annotations

import copy
import os
import sys
from typing import List, Optional, Sequence, Tuple

from pptx import Presentation
from pptx.util import Emu, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.environ.get(
    "DECK_TEMPLATE",
    r"C:\Users\Rayti\Downloads\Шаблон презентации Хакатон (1).pptx")
OUTPUT = os.path.join(HERE, "Олимп — презентация.pptx")

Chunk = Tuple[str, bool]          # (текст, жирный)
Paragraph = List[Chunk]

A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

# --------------------------------------------------------------------------
#  содержание слайдов
# --------------------------------------------------------------------------

TITLE = ["ОЛИМП", "НАВИГАТОР ОЛИМПИАДНЫХ ЛЬГОТ"]

DIRECTION: List[Paragraph] = [
    [("Подземелье знаний. ", True),
     ("Решение, которое помогает школьнику не потеряться в самой запутанной "
      "части пути в вуз — в олимпиадных льготах.", False)],
    [("Диплом олимпиады даёт БВИ или 100 баллов, но правила разбросаны по сотням "
      "PDF-приложений приёмных комиссий. Мы превратили их в поиск, который "
      "отвечает за два клика.", False)],
]

AUDIENCE: List[Paragraph] = [
    [("Школьники 9–11 классов. ", True),
     ("Уже участвуют в олимпиадах или только выбирают, куда идти. Им нужен ответ: "
      "что мой диплом уже даёт и чего не хватает.", False)],
    [("Классные руководители и учителя-предметники. ", True),
     ("Отвечают за поступление выпускников и помогают с выбором. Сегодня им помогает "
      "ссылка «Поделиться»: результат ученика уходит в чат одной кнопкой.", False)],
    [("Родители. ", True),
     ("Хотят понимать, что даёт ребёнку подготовка к олимпиадам.", False)],
    [("Всем троим сегодня приходится читать первоисточник — приложения к правилам "
      "приёма, написанные не для школьников.", False)],
]

PROBLEM: List[Paragraph] = [
    [("Диплом — не универсальный ключ. ", True),
     ("Одна олимпиада даёт БВИ в одном вузе, 100 баллов в другом и ничего в третьем.", False)],
    [("Правила спрятаны в PDF. ", True),
     ("У ИТМО отдельные приложения на БВИ и на 100 баллов, у ВШЭ — документ на "
      "67 программ, у МГТУ им. Баумана — 10 групп направлений. Одно приложение — "
      "до 10 000 символов сплошного перечисления.", False)],
    [("Решает профиль, а не название. ", True),
     ("У НТО 42 профиля: БВИ в ИТМО даёт «разработка мобильных приложений», "
      "а не НТО вообще.", False)],
    [("Про ЕГЭ узнают поздно. ", True),
     ("Почти везде нужен результат ≥75 по профильному предмету, у ВШЭ местами "
      "85 и 90 — без этого диплом не работает.", False)],
    [("Каждый год всё меняется. ", True),
     ("Документы обновляются, прошлогодние ссылки умирают, следить за этим некому.", False)],
]

SOLUTION: List[Paragraph] = [
    [("Сайт и мини-приложение в MAX: три сценария поиска и доп. баллы.", True)],
    [("Куда с моей олимпиадой. ", True),
     ("Ученик вводит олимпиаду, уточняет профиль и получает список вузов, "
      "а по клику на вуз — таблицу: БВИ или 100 баллов, уровень, класс, "
      "какой ЕГЭ подтвердить.", False)],
    [("Что нужно для вуза. ", True),
     ("Выбирает вуз и направление и видит все олимпиады, которые туда ведут.", False)],
    [("Мои дипломы. ", True),
     ("Ученик добавляет диплом (олимпиада, профиль, степень, класс, год) и видит, "
      "где он даёт льготу, а где нет — и почему: «только победителям», «за другой класс».", False)],
    [("Доп. баллы. ", True),
     ("ГТО, аттестат с отличием, спорт: сколько баллов добавит вуз, с лимитом "
      "суммы и ссылкой на страницу документа. Сейчас данные по 7 вузам.", False)],
    [("Под капотом. ", True),
     ("Разбор документов приёмных комиссий в базу: 49 000 строк таблиц и 59 000 связей "
      "«олимпиада → направление». Каждая строка ведёт на документ вуза, ссылки "
      "обновляются скриптом. Результат можно отправить в чат кнопкой «Поделиться».", False)],
]

VALUE: List[Paragraph] = [
    [("Экономит часы на каждого ученика. ", True),
     ("Вместо десятка PDF и звонков в приёмную комиссию — ответ за два клика.", False)],
    [("Делает выбор олимпиады осознанным. ", True),
     ("Видно, какая олимпиада закрывает больше вузов из списка мечты: "
      "готовиться можно прицельно, а не наугад.", False)],
    [("Честно про пробелы. ", True),
     ("Где в базе нет таблицы вуза, так и написано: это не «льготы нет». Правила, "
      "разобранные автоматически и не сверенные человеком, помечены.", False)],
    [("Охват. ", True),
     ("Каждый выпускной класс страны — и каждый год заново, потому что правила "
      "обновляются. В базе уже 39 вузов, 659 направлений, 173 олимпиады "
      "и 635 профилей.", False)],
]

CONCLUSION: List[Paragraph] = [
    [("Мы отвечаем на вопрос, на который не отвечает никто. ", True),
     ("Сайт вуза говорит, что нужно ему. Школьнику нужно обратное: «куда меня "
      "возьмут с тем, что у меня уже есть». Наш поиск работает именно в эту "
      "сторону — и на данных, у которых есть источник: страница и цитата документа.", False)],
    [("Это не идея, а работающий сервис. ", True),
     ("Он открыт по адресу ideafix.patissons.tech и как мини-приложение в MAX. Данные — "
      "приёмная кампания 2026; правила 2027 вузы публикуют позже, после этого базу "
      "пересобираем (около минуты). Точность данных ещё предстоит измерить выборочным "
      "аудитом: мы не утверждаем «ноль ошибок».", False)],
]


# --------------------------------------------------------------------------
#  работа с шаблоном
# --------------------------------------------------------------------------

def body_shape(slide):
    """Самая крупная текстовая рамка — в этом шаблоне это блок с подсказкой."""
    best, best_area = None, 0
    for shape in slide.shapes:
        if not shape.has_text_frame or not shape.text_frame.text.strip():
            continue
        area = int(shape.width) * int(shape.height)
        if area > best_area:
            best, best_area = shape, area
    return best


def normalize_frame(shape) -> None:
    """
    В шаблоне у текстовых блоков включён автоподгон (normAutofit / spAutoFit):
    при нашем объёме текста он ужимает шрифт до нечитаемого. Выключаем его,
    размеры задаём сами.
    """
    body_pr = shape.text_frame._txBody.find(f"{A_NS}bodyPr")
    if body_pr is None:
        return
    for tag in ("normAutofit", "spAutoFit", "noAutofit"):
        for node in body_pr.findall(f"{A_NS}{tag}"):
            body_pr.remove(node)
    body_pr.append(body_pr.makeelement(f"{A_NS}noAutofit", {}))


def set_paragraph_spacing(paragraph, points: int) -> None:
    """Отбивка после абзаца: шаблонные 12 pt слишком щедры для нашего объёма."""
    p_pr = paragraph._p.find(f"{A_NS}pPr")
    if p_pr is None:
        p_pr = paragraph._p.makeelement(f"{A_NS}pPr", {})
        paragraph._p.insert(0, p_pr)
    for tag, value in (("spcBef", 0), ("spcAft", points)):
        node = p_pr.find(f"{A_NS}{tag}")
        if node is None:
            node = p_pr.makeelement(f"{A_NS}{tag}", {})
            p_pr.append(node)
        for child in list(node):
            node.remove(child)
        node.append(node.makeelement(f"{A_NS}spcPts", {"val": str(value * 100)}))
    # межстрочный интервал шаблона местами 115% — для плотного текста избыточно
    for node in p_pr.findall(f"{A_NS}lnSpc"):
        p_pr.remove(node)
    ln_spc = p_pr.makeelement(f"{A_NS}lnSpc", {})
    ln_spc.append(ln_spc.makeelement(f"{A_NS}spcPct", {"val": "100000"}))
    p_pr.insert(0, ln_spc)


def set_paragraphs(shape, paragraphs: Sequence[Paragraph],
                   size_pt: Optional[float] = None, spacing_pt: int = 6) -> None:
    """Переписывает текст рамки, сохраняя оформление шаблона."""
    normalize_frame(shape)
    frame = shape.text_frame
    template_p = copy.deepcopy(frame.paragraphs[0]._p)

    for p in list(frame._txBody.findall(f"{A_NS}p"))[1:]:
        frame._txBody.remove(p)

    def fill(paragraph, chunks: Paragraph) -> None:
        runs = paragraph.runs
        if not runs:
            return
        template_r = copy.deepcopy(runs[0]._r)
        for extra in runs[1:]:
            extra._r.getparent().remove(extra._r)
        # в шаблонных абзацах есть принудительные переносы строк — после замены
        # текста они превращаются в пустые строки
        for br in paragraph._p.findall(f"{A_NS}br"):
            paragraph._p.remove(br)
        for index, (text, bold) in enumerate(chunks):
            if index:
                paragraph._p.append(copy.deepcopy(template_r))
            run = paragraph.runs[index]
            run.text = text
            run.font.bold = bold
            if size_pt:
                run.font.size = Pt(size_pt)
            # шаблонный Open Sans Light в жирном начертании почти не отличается
            # от обычного — для подзаголовков берём обычный Open Sans
            if bold:
                r_pr = run._r.find(f"{A_NS}rPr")
                for tag in ("latin", "ea", "cs"):
                    node = r_pr.find(f"{A_NS}{tag}") if r_pr is not None else None
                    if node is not None:
                        node.set("typeface", "Open Sans")
        set_paragraph_spacing(paragraph, spacing_pt)

    fill(frame.paragraphs[0], paragraphs[0])
    for chunks in paragraphs[1:]:
        frame._txBody.append(copy.deepcopy(template_p))
        fill(frame.paragraphs[-1], chunks)


def set_title(slide, lines: Sequence[str]) -> None:
    set_paragraphs(body_shape(slide), [[(line, True)] for line in lines], spacing_pt=0)


def drop_slide(prs, index: int) -> None:
    slides = prs.slides._sldIdLst
    slides.remove(list(slides)[index])


def strip_comments(path: str) -> int:
    """
    В шаблоне остались рабочие комментарии его авторов: в сдаваемой презентации
    они лишние, а ещё дают дубли authorId при валидации. Вырезаем их вместе
    со ссылками из слайдов и списка типов.
    """
    import re
    import shutil
    import zipfile

    source = zipfile.ZipFile(path)
    names = source.namelist()
    drop = [n for n in names
            if n.startswith("ppt/comments/") or n == "ppt/authors.xml"]
    if not drop:
        source.close()
        return 0

    tmp = path + ".tmp"
    ext_re = re.compile(r'<p:ext uri="\{6950BFC3-D8DA-4A85-94F7-54DA5524770B\}">.*?</p:ext>', re.S)
    rel_re = re.compile(r'<Relationship[^>]*(?:comments|authors)[^>]*/>', re.I)
    type_re = re.compile(r'<Override[^>]*PartName="/ppt/(?:comments/[^"]*|authors\.xml)"[^>]*/>', re.I)

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for item in source.infolist():
            if item.filename in drop:
                continue
            data = source.read(item.filename)
            if item.filename.startswith("ppt/slides/slide") and item.filename.endswith(".xml"):
                data = ext_re.sub("", data.decode("utf-8")).encode("utf-8")
            elif item.filename.endswith(".rels"):
                data = rel_re.sub("", data.decode("utf-8")).encode("utf-8")
            elif item.filename == "[Content_Types].xml":
                data = type_re.sub("", data.decode("utf-8")).encode("utf-8")
            out.writestr(item, data)
    source.close()
    shutil.move(tmp, path)
    return len(drop)


def main() -> int:
    if not os.path.exists(TEMPLATE):
        print(f"Шаблон не найден: {TEMPLATE}")
        return 1
    prs = Presentation(TEMPLATE)

    set_title(prs.slides[0], TITLE)

    # направление: оставляем карточку «Подземелье знаний» (01), остальные убираем
    direction = prs.slides[3]
    pictures = sorted((s for s in direction.shapes if s.shape_type == 13),
                      key=lambda s: int(s.left))
    for pic in pictures[1:]:
        pic._element.getparent().remove(pic._element)
    if pictures:
        keep = pictures[0]
        scale = 1.35
        keep.height = Emu(int(int(keep.height) * scale))
        keep.width = Emu(int(int(keep.width) * scale))
        keep.left = Emu(int(9.85 * 914400) - int(keep.width))
        keep.top = Emu(int(0.52 * 914400))
    shape = body_shape(direction)
    shape.left, shape.top = Emu(int(0.34 * 914400)), Emu(int(1.60 * 914400))
    shape.width, shape.height = Emu(int(6.6 * 914400)), Emu(int(2.6 * 914400))
    set_paragraphs(shape, DIRECTION, size_pt=12, spacing_pt=10)

    # содержательные слайды: блок текста слева, декор шаблона справа
    # top больше там, где заголовок слайда занимает две строки
    for index, paragraphs, size, top in ((4, AUDIENCE, 11.5, 1.55), (5, PROBLEM, 11, 1.20),
                                         (6, SOLUTION, 11, 1.20), (7, VALUE, 11.5, 1.20),
                                         (8, CONCLUSION, 12, 1.20)):
        slide = prs.slides[index]
        shape = body_shape(slide)
        shape.left = Emu(int(0.34 * 914400))
        shape.top = Emu(int(top * 914400))
        shape.width = Emu(int(5.6 * 914400))
        shape.height = Emu(int(3.4 * 914400))      # ниже 4.6" начинаются логотипы
        set_paragraphs(shape, paragraphs, size_pt=size, spacing_pt=7)

    drop_slide(prs, 1)      # служебный слайд «как работать с шаблоном»

    prs.save(OUTPUT)
    removed = strip_comments(OUTPUT)
    print(f"Готово: {OUTPUT}" + (f" (убрано частей с комментариями: {removed})" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
