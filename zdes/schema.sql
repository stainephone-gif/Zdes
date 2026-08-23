-- Схема соответствует §8.3 ТЗ. SQLite выбран сознательно: на объёме
-- в несколько сотен записей PostGIS не нужен, а разворачивание где угодно
-- и хранение базы в git при команде из одного человека важнее.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS person (
    id                 INTEGER PRIMARY KEY,
    wikidata_id        TEXT UNIQUE,
    full_name          TEXT NOT NULL,
    name_normalized    TEXT NOT NULL,
    surname            TEXT,
    birth_year         INTEGER,
    death_year         INTEGER,
    occupation         TEXT,
    short_description  TEXT,              -- абзац «чем важен»
    description_status TEXT DEFAULT 'empty',  -- empty | drafted | verified
    article_url        TEXT,
    portrait_url       TEXT,
    portrait_license   TEXT,
    verified_at        TEXT,
    verified_by        TEXT
);
CREATE INDEX IF NOT EXISTS idx_person_surname ON person(surname);

CREATE TABLE IF NOT EXISTS place (
    id                  INTEGER PRIMARY KEY,
    osm_id              TEXT UNIQUE,
    wikidata_id         TEXT,
    address             TEXT,
    lat                 REAL NOT NULL,
    lon                 REAL NOT NULL,
    building_year       INTEGER,
    architect_person_id INTEGER REFERENCES person(id),
    description         TEXT
);

CREATE TABLE IF NOT EXISTS plaque (
    id            INTEGER PRIMARY KEY,
    osm_id        TEXT UNIQUE NOT NULL,
    place_id      INTEGER REFERENCES place(id),
    person_id     INTEGER REFERENCES person(id),
    inscription   TEXT,
    lat           REAL NOT NULL,
    lon           REAL NOT NULL,
    relation_type TEXT,        -- lived | worked | born | died | event
    relation_years TEXT,
    installed_year INTEGER,
    photo_url     TEXT,
    -- откуда взялась привязка к персоне: это же определяет цену верификации
    resolution    TEXT DEFAULT 'unresolved',  -- wikidata | matched | manual | unresolved
    match_score   REAL,
    status        TEXT DEFAULT 'draft'        -- draft | deferred | published | archived
);
CREATE INDEX IF NOT EXISTS idx_plaque_geo ON plaque(lat, lon);
CREATE INDEX IF NOT EXISTS idx_plaque_status ON plaque(status);
CREATE INDEX IF NOT EXISTS idx_plaque_person ON plaque(person_id);

CREATE TABLE IF NOT EXISTS work (
    id          INTEGER PRIMARY KEY,
    wikidata_id TEXT UNIQUE,
    person_id   INTEGER NOT NULL REFERENCES person(id),
    title       TEXT NOT NULL,
    work_type   TEXT,      -- building | bridge | tower | monument | interior
    authorship  TEXT,      -- architect | engineer | sculptor
    lat         REAL,
    lon         REAL,
    built_year  INTEGER,
    status      TEXT DEFAULT 'draft'
);
CREATE INDEX IF NOT EXISTS idx_work_person ON work(person_id);

CREATE TABLE IF NOT EXISTS content_link (
    id              INTEGER PRIMARY KEY,
    person_id       INTEGER NOT NULL REFERENCES person(id),
    type            TEXT NOT NULL,   -- book | music | film | archive
    title           TEXT,
    url             TEXT NOT NULL,
    provider        TEXT,
    last_checked_at TEXT,
    is_alive        INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_link_person ON content_link(person_id);

CREATE TABLE IF NOT EXISTS relation (
    id            INTEGER PRIMARY KEY,
    from_type     TEXT NOT NULL,   -- person | place | work
    from_id       INTEGER NOT NULL,
    to_type       TEXT NOT NULL,
    to_id         INTEGER NOT NULL,
    relation_kind TEXT NOT NULL,   -- other_address | workplace | significant_place
                                   -- | work | known_person | neighbour_in_time
                                   -- | mentioned_in_text
    caption       TEXT NOT NULL,   -- причина связи; без неё связь не показывается
    confidence    TEXT NOT NULL,   -- computed | wikidata | editor
    source_id     INTEGER REFERENCES source(id),
    status        TEXT DEFAULT 'draft'
);
CREATE INDEX IF NOT EXISTS idx_relation_from ON relation(from_type, from_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_relation_unique
    ON relation(from_type, from_id, to_type, to_id, relation_kind);

CREATE TABLE IF NOT EXISTS source (
    id           INTEGER PRIMARY KEY,
    entity_type  TEXT NOT NULL,
    entity_id    INTEGER NOT NULL,
    url          TEXT NOT NULL,
    title        TEXT,
    license      TEXT,
    retrieved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_entity ON source(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS recognition_event (
    id             INTEGER PRIMARY KEY,
    device_id_hash TEXT,
    created_at     TEXT NOT NULL,
    lat REAL, lon REAL,
    ocr_text       TEXT,
    engine         TEXT,
    top_score      REAL,
    candidates     TEXT,       -- JSON
    chosen_plaque_id INTEGER,
    outcome        TEXT        -- auto | chosen | manual | failed
);
