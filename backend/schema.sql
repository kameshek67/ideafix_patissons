-- Схема БД «Олимпиада → ВУЗ» (SQLite).
-- Нормализованная часть: universities / programs / benefits.
-- Поисковая часть: olympiads / olympiad_aliases / benefit_olympiads /
--                  benefit_keywords / search_index (FTS5, создаётся в ingest_data.py:
--                  contentless-таблица, rowid которой равен benefits.id).

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS search_index;
DROP TABLE IF EXISTS benefit_keywords;
DROP TABLE IF EXISTS benefit_olympiads;
DROP TABLE IF EXISTS olympiad_profiles;
DROP TABLE IF EXISTS olympiad_aliases;
DROP TABLE IF EXISTS olympiads;
DROP TABLE IF EXISTS benefits;
DROP TABLE IF EXISTS programs;
DROP TABLE IF EXISTS universities;
DROP TABLE IF EXISTS university_documents;
DROP TABLE IF EXISTS ingest_log;
DROP TABLE IF EXISTS meta;

CREATE TABLE universities (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    short_name  TEXT NOT NULL,
    region      TEXT NOT NULL DEFAULT '',
    -- город/площадка для показа в таблицах («Приволжский ФО» -> «Казань»)
    city        TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    -- запасная ссылка на документ вуза: берётся из самого частого источника
    site_url    TEXT NOT NULL DEFAULT '',
    -- стабильная страница раздела «Документы / Олимпиады» (university_pages.py).
    -- Именно она показывается пользователю: прямые файлы меняются каждый сезон.
    docs_url    TEXT NOT NULL DEFAULT '',
    docs_title  TEXT NOT NULL DEFAULT '',
    -- укрупнённый фильтр для фронта: Москва / Санкт-Петербург / Регионы
    region_group TEXT NOT NULL DEFAULT 'Регионы'
);

CREATE TABLE programs (
    id                   INTEGER PRIMARY KEY,
    university_id        INTEGER NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
    faculty_or_direction TEXT NOT NULL,
    profile_name         TEXT NOT NULL DEFAULT '',
    code                 TEXT NOT NULL DEFAULT '',
    note                 TEXT NOT NULL DEFAULT '',
    -- название документа приёмной комиссии и отдельно ссылка на него
    source_title         TEXT NOT NULL DEFAULT '',
    source_url           TEXT NOT NULL DEFAULT '',
    source_sheet         TEXT NOT NULL DEFAULT '',
    sort_order           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_programs_university ON programs(university_id);
CREATE INDEX idx_programs_code ON programs(code);

CREATE TABLE benefits (
    id                  INTEGER PRIMARY KEY,
    program_id          INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    benefit_type        TEXT NOT NULL CHECK (benefit_type IN (
                            'БВИ', '100 баллов', 'Особое право (БВИ/100)',
                            'Фаст-трек', 'ИД (доп. баллы)')),
    raw_conditions_text TEXT NOT NULL,
    -- detailed — строка таблицы «олимпиада × профиль» (из подробного листа
    --            или разобранная из перечисления в «Базе»)
    -- summary  — текстовое правило вуза без названий олимпиад (идёт в примечания)
    -- derived  — строка, выведенная из правила «любая олимпиада перечня по профилю X»
    -- raw      — исходное перечисление из «Базы», уже разложенное в строки таблицы;
    --            хранится для трассировки, в выдачу не попадает
    layer               TEXT NOT NULL DEFAULT 'summary'
                        CHECK (layer IN ('summary', 'detailed', 'derived', 'raw')),
    olympiad_profile    TEXT NOT NULL DEFAULT '',
    olympiad_subject    TEXT NOT NULL DEFAULT '',
    level               TEXT NOT NULL DEFAULT '',
    winner_role         TEXT NOT NULL DEFAULT '',
    grade               TEXT NOT NULL DEFAULT '',
    confirm_subject     TEXT NOT NULL DEFAULT '',
    min_ege             TEXT NOT NULL DEFAULT '',
    award_subject       TEXT NOT NULL DEFAULT '',
    years               TEXT NOT NULL DEFAULT '',
    note                TEXT NOT NULL DEFAULT '',
    source_title        TEXT NOT NULL DEFAULT '',
    source_url          TEXT NOT NULL DEFAULT '',
    source_sheet        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_benefits_program ON benefits(program_id);
CREATE INDEX idx_benefits_type ON benefits(benefit_type);
CREATE INDEX idx_benefits_layer ON benefits(layer);

CREATE TABLE olympiads (
    id             INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    short_name     TEXT NOT NULL,
    squash_key     TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'rsosh',
    is_featured    INTEGER NOT NULL DEFAULT 0,
    mentions       INTEGER NOT NULL DEFAULT 0,
    bvi_count      INTEGER NOT NULL DEFAULT 0,
    sto_count      INTEGER NOT NULL DEFAULT 0,
    uni_count      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_olympiads_mentions ON olympiads(mentions DESC);

CREATE TABLE olympiad_aliases (
    id           INTEGER PRIMARY KEY,
    olympiad_id  INTEGER NOT NULL REFERENCES olympiads(id) ON DELETE CASCADE,
    alias        TEXT NOT NULL,
    squash_alias TEXT NOT NULL,
    is_generic   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (olympiad_id, squash_alias)
);
CREATE INDEX idx_alias_squash ON olympiad_aliases(squash_alias);

-- Профили олимпиады: у НТО их несколько десятков, и льгота даётся
-- за пару «олимпиада + профиль», а не за олимпиаду целиком.
CREATE TABLE olympiad_profiles (
    id          INTEGER PRIMARY KEY,
    olympiad_id INTEGER NOT NULL REFERENCES olympiads(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    squash_key  TEXT NOT NULL,
    level       TEXT NOT NULL DEFAULT '',   -- преобладающий уровень пары «олимпиада+профиль»
    mentions    INTEGER NOT NULL DEFAULT 0,
    bvi_count   INTEGER NOT NULL DEFAULT 0,
    sto_count   INTEGER NOT NULL DEFAULT 0,
    uni_count   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (olympiad_id, squash_key)
);
CREATE INDEX idx_profiles_olympiad ON olympiad_profiles(olympiad_id);

-- Связка «льгота ↔ олимпиада (+профиль)»: ядро обратного поиска.
CREATE TABLE benefit_olympiads (
    id          INTEGER PRIMARY KEY,
    benefit_id  INTEGER NOT NULL REFERENCES benefits(id) ON DELETE CASCADE,
    olympiad_id INTEGER NOT NULL REFERENCES olympiads(id) ON DELETE CASCADE,
    profile_id  INTEGER REFERENCES olympiad_profiles(id) ON DELETE SET NULL,
    profile     TEXT NOT NULL DEFAULT '',
    level       TEXT NOT NULL DEFAULT '',
    winner_role TEXT NOT NULL DEFAULT '',
    matched_via TEXT NOT NULL DEFAULT 'column',   -- column | text
    UNIQUE (benefit_id, olympiad_id, profile, level)
);
CREATE INDEX idx_bo_olympiad ON benefit_olympiads(olympiad_id);
CREATE INDEX idx_bo_benefit ON benefit_olympiads(benefit_id);
CREATE INDEX idx_bo_profile ON benefit_olympiads(profile_id);

-- Ключевые слова, вытащенные алгоритмически из текста условий.
CREATE TABLE benefit_keywords (
    id         INTEGER PRIMARY KEY,
    benefit_id INTEGER NOT NULL REFERENCES benefits(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,   -- level | role | grade | ege | subject | olympiad
    keyword    TEXT NOT NULL,
    UNIQUE (benefit_id, kind, keyword)
);
CREATE INDEX idx_keywords_keyword ON benefit_keywords(keyword);
CREATE INDEX idx_keywords_kind ON benefit_keywords(kind);

-- Файлы, найденные на странице вуза скриптом refresh_sources.py
CREATE TABLE university_documents (
    id            INTEGER PRIMARY KEY,
    university_id INTEGER NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    checked_at    TEXT NOT NULL DEFAULT '',
    UNIQUE (university_id, url)
);
CREATE INDEX idx_unidocs_uni ON university_documents(university_id);

CREATE TABLE ingest_log (
    id            INTEGER PRIMARY KEY,
    sheet         TEXT NOT NULL,
    rows_read     INTEGER NOT NULL DEFAULT 0,
    rows_ingested INTEGER NOT NULL DEFAULT 0,
    benefits      INTEGER NOT NULL DEFAULT 0,
    comment       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
