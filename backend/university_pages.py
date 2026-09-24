# -*- coding: utf-8 -*-
"""
Справочник страниц приёмных комиссий — главный редактируемый файл проекта.

Идея: прямая ссылка на PDF живёт один приёмный сезон («…/2026/Lgoty.pdf»), а адрес
раздела «Документы / Олимпиады» у вуза меняется редко. Поэтому в базе мы храним
ссылку на СТРАНИЦУ, а конкретные файлы с неё раз в год собирает `refresh_sources.py`
и складывает в таблицу university_documents. Руками нужно поддерживать только этот файл.

Как добавить вуз: ключ — характерная подстрока его названия из «Базы» (в нижнем
регистре, без пробелов и знаков — так же, как squash()), значение — Page(...).

status:
    verified — обход нашёл на странице документы об олимпиадах и приёме
    page     — страница верная по смыслу, но файлы отдаются скриптом или лежат текстом
    guarded  — сайт закрыт от автоматических запросов (403 или таймаут), в браузере открывается
    todo     — ссылка временная, нужен адрес раздела с документами
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    title: str          # как подписать кнопку: «Правила приёма и приложения»
    url: str            # стабильный адрес раздела
    status: str = "todo"
    note: str = ""


PAGES = {
    # --- проверено: на странице лежат нужные файлы -------------------------
    "казанский": Page(
        "Правила приёма КФУ и приложения",
        "https://admissions.kpfu.ru/dokumenty/bakalavriat-specialitet/pravila-priyoma/",
        "verified", "Приложение 3 — порядок учёта результатов олимпиад"),
    "итмо": Page(
        "Поступление на бакалавриат ИТМО: перечни олимпиад",
        "https://abit.itmo.ru/bachelor",
        "verified", "rsosh_bvi / rsosh_100 / vsosh — три отдельных PDF"),
    "уральскийфедеральный": Page(
        "Абитуриенту УрФУ: документы приёмной кампании",
        "https://urfu.ru/ru/applicant/",
        "verified", "правила приёма и льготы олимпиадникам"),
    "горный": Page(
        "Приёмная комиссия Горного университета: документы",
        "https://priem.spmi.ru/",
        "verified", "в списке есть «Соответствие профилей ВсОШ и перечневых олимпиад»"),
    "иннополис": Page(
        "Сведения об образовательной организации: приём",
        "https://innopolis.university/sveden/apply/",
        "verified", "«Олимпиады, учитываемые для реализации особых прав»"),
    "финансовыйуниверситет": Page(
        "Соответствие профилей олимпиад — Финуниверситет",
        "https://www.fa.ru/for-applicants/priyemka/sootvetstvie-profilej-olimpiad/",
        "verified", "перечень олимпиад школьников за 10–11 класс"),
    "рэуимгвплеханова": Page(
        "Приёмная комиссия РЭУ: поступающим",
        "https://www.rea.ru/pk/entrant",
        "verified", "виджет «Поиск олимпиад» + правила приёма"),
    "спбпу": Page(
        "Политех: особые права победителям олимпиад",
        "https://www.spbstu.ru/abit/bachelor/oznakomitsya-with-the-regulations/olympics/",
        "verified", "bachelor_olympic_order.pdf"),
    "мгуим": Page(
        "ЦПК МГУ: документы приёмной комиссии",
        "https://cpk.msu.ru/",
        "verified", "olymp_benefits.pdf и olymp_disciplines.pdf лежат прямо на главной"),
    "ранхигс": Page(
        "РАНХиГС: олимпиады",
        "https://www.ranepa.ru/bakalavriat/olimpiady/",
        "verified", "четыре отдельных перечня: БВИ/100 баллов × РСОШ/ВсОШ"),
    "рггу": Page(
        "РГГУ: бакалавриат",
        "https://www.rsuh.ru/abitur/bachelor/",
        "verified", "«Особые права для победителей и призеров олимпиад»"),
    "авиационный": Page(
        "МАИ: победителям и призёрам олимпиад",
        "https://priem.mai.ru/orders/contest-winners/",
        "verified", "перечень олимпиад школьников приложением к приказу"),

    # --- страница верная, файлы на ней рендерит скрипт или текст -----------
    "нияумифи": Page(
        "Победителям и призёрам олимпиад — НИЯУ МИФИ",
        "https://admission.mephi.ru/admission/baccalaureate-and-specialty/specials/winners",
        "page", "таблица соответствия олимпиад направлениям выводится на самой странице"),
    "новосибирский": Page(
        "НГУ: льготы победителям и призёрам олимпиад",
        "https://www.nsu.ru/n/education/apply-info/olimpiady-privilege/", "verified",
        "перечень олимпиад РСОШ"),
    "центральныйуниверситет": Page(
        "Центральный университет: олимпиады",
        "https://cu.ru/olympiad", "page"),
    "мгимо": Page(
        "МГИМО: льготы при поступлении",
        "https://abiturient.mgimo.ru/bakalavriat/lgoty", "page"),
    "мирэа": Page(
        "РТУ МИРЭА: олимпиады школьников",
        "https://priem.mirea.ru/olympiads", "guarded", "403 для скриптов, в браузере открывается"),
    "мисис": Page(
        "НИТУ МИСИС: олимпиады школьников",
        "https://misis.ru/applicants/admission/baccalaureate-and-specialty/olympiad/school/",
        "guarded"),
    "рудн": Page("РУДН: олимпиады", "https://priem.rudn.ru/olympiady", "verified", "4 документа"),
    "лэти": Page(
        "ЛЭТИ: льготы и привилегии олимпиадникам",
        "https://etu.ru/ru/abiturientam/olimpiady-shkolnikov/lgoty-i-privilegii", "verified"),

    # --- адреса разделов, присланные вручную ------------------------------
    "ниувшэ": Page(
        "НИУ ВШЭ: олимпиады и особые права",
        "https://ba.hse.ru/bolimp", "verified",
        "12 файлов «Льготы победителям и призёрам олимпиад» — по кампусам и годам"),
    "спбгу": Page(
        "СПбГУ: программы бакалавриата и документы",
        "https://abiturient.spbu.ru/programs/bakalavriat/", "verified", "7 документов"),
    "сеченов": Page(
        "Сеченовский университет: правила приёма",
        "https://priem.sechenov.ru/undergraduate/pravila-priema/", "verified",
        "правила приёма и приложения"),
    "сибирскийфедеральный": Page(
        "СФУ: олимпиады школьников",
        "https://sfu.ru/ru/admission/bachelor/olymp", "verified"),
    "мэи": Page(
        "НИУ «МЭИ»: особые права",
        "https://pk-mpei.ru/info/Oprava", "verified"),
    "миэт": Page(
        "МИЭТ: поступление",
        "https://miet.ru/page/188684", "verified"),

    # страница открывается, но файлы отдаются скриптом или лежат текстом
    "пирогов": Page(
        "РНИМУ им. Пирогова: правила приёма",
        "https://rsmu.ru/abitur/specialitet/rules", "page"),
    "мфти": Page(
        "МФТИ: поступление на бакалавриат",
        "https://pk.mipt.ru/bachelor/", "page",
        "раздел без года в адресе, в отличие от прежней ссылки"),
    "мгюа": Page(
        "МГЮА: приёмная кампания",
        "https://msal.ru/content/abiturientam/priemnaya-kampaniya/", "page"),

    # сайт закрыт от автоматических запросов — в браузере открывается
    "баумана": Page(
        "МГТУ им. Баумана: документы приёмной комиссии",
        "https://mirror.bmstu.ru/documents", "guarded"),
    "губкина": Page(
        "РГУ нефти и газа им. Губкина: перечень олимпиад",
        "https://gubkin.ru/school_olympiad/olympiad_list2.php", "guarded"),
}

# слова, по которым скрипт узнаёт нужный документ на странице вуза
DOCUMENT_KEYWORDS = (
    "олимпиад", "особ", "бви", "без вступительных", "перечн",
    "правила приёма", "правила приема", "приложение",
)
