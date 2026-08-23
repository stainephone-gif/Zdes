# -*- coding: utf-8 -*-
"""Импорт табличек из OSM с обогащением из Wikidata.

Задача импорта — довести запись до состояния, в котором редактору остаётся
её подтвердить, а не заполнить. Всё, что можно вывести автоматически,
выводится здесь; всё, что выведено, помечается как непроверенное.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote_plus

from . import db, osm, wikidata
from .matcher import fold, parse_inscription

# --------------------------------------------------------------------------
# Ссылки на внешние произведения
# --------------------------------------------------------------------------

# Пустая ссылка хуже отсутствующей: генерируем только те типы, которые
# осмысленны для рода занятий человека.
OCCUPATION_LINKS = {
    'book': ('писател', 'поэт', 'драматург', 'публицист', 'литератур', 'переводчик'),
    'music': ('композитор', 'музыкант', 'пианист', 'скрипач', 'дирижёр', 'дирижер',
              'певец', 'певица', 'виолончелист'),
    'film': ('режисс', 'актёр', 'актер', 'актриса', 'кинематограф', 'сценарист'),
}

LINK_TEMPLATES = {
    'book': ('Литрес', 'https://www.litres.ru/search/?q={q}'),
    'music': ('Яндекс Музыка', 'https://music.yandex.ru/search?text={q}'),
    'film': ('Кинопоиск', 'https://www.kinopoisk.ru/index.php?kp_query={q}'),
}


def content_links_for(person: wikidata.Person) -> list[dict]:
    occ = (person.occupation or '').lower()
    links = []
    for link_type, markers in OCCUPATION_LINKS.items():
        if any(m in occ for m in markers):
            provider, template = LINK_TEMPLATES[link_type]
            links.append({
                'type': link_type, 'provider': provider,
                'title': f'{person.full_name} — искать в «{provider}»',
                'url': template.format(q=quote_plus(person.full_name)),
            })
    return links


# --------------------------------------------------------------------------
# Вычисляемые связи (US-2.3b)
# --------------------------------------------------------------------------

NEIGHBOUR_RADIUS_M = 300.0

RELATION_SQL = (
    'INSERT OR IGNORE INTO relation '
    '(from_type, from_id, to_type, to_id, relation_kind, caption, confidence, status) '
    "VALUES (?,?,?,?,?,?,?,'draft')"
)


def insert_relation(conn, rel: dict) -> None:
    """Уникальность связи — по паре сущностей и типу, а не по подписи."""
    conn.execute(RELATION_SQL, (
        rel['from_type'], rel['from_id'], rel['to_type'], rel['to_id'],
        rel['relation_kind'], rel['caption'], rel['confidence'],
    ))


@dataclass
class PlaqueRow:
    plaque_id: int
    person_id: int
    lat: float
    lon: float
    surname: str
    residence_years: tuple[int, int] | None
    life_years: tuple[int | None, int | None]


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def computed_relations(rows: list[PlaqueRow]) -> list[dict]:
    """Связи, выводимые из уже имеющихся данных. Без единого внешнего запроса."""
    relations: list[dict] = []

    # 1. Другие адреса того же человека
    by_person: dict[int, list[PlaqueRow]] = {}
    for row in rows:
        by_person.setdefault(row.person_id, []).append(row)
    for person_rows in by_person.values():
        if len(person_rows) < 2:
            continue
        for a in person_rows:
            for b in person_rows:
                if a.plaque_id == b.plaque_id:
                    continue
                years = (f' в {b.residence_years[0]}–{b.residence_years[1]}'
                         if b.residence_years else '')
                relations.append({
                    'from_type': 'plaque', 'from_id': a.plaque_id,
                    'to_type': 'plaque', 'to_id': b.plaque_id,
                    'relation_kind': 'other_address',
                    'caption': f'Ещё один его адрес{years}',
                    'confidence': 'computed',
                })

    # 2. Соседи по месту и времени
    for a in rows:
        for b in rows:
            if a.person_id >= b.person_id:
                continue
            if db.haversine_m(a.lat, a.lon, b.lat, b.lon) > NEIGHBOUR_RADIUS_M:
                continue

            # Если у обоих известны годы проживания — это сильное утверждение
            if a.residence_years and b.residence_years and \
                    _overlap(a.residence_years, b.residence_years):
                caption = 'Жил в соседнем доме в те же годы'
            else:
                # Иначе честнее сказать «современник», а не выдумывать соседство
                la, lb = a.life_years, b.life_years
                if not all((la[0], la[1], lb[0], lb[1])) or \
                        not _overlap((la[0], la[1]), (lb[0], lb[1])):
                    continue
                caption = 'Современник, его табличка совсем рядом'

            for x, y in ((a, b), (b, a)):
                relations.append({
                    'from_type': 'plaque', 'from_id': x.plaque_id,
                    'to_type': 'plaque', 'to_id': y.plaque_id,
                    'relation_kind': 'neighbour_in_time',
                    'caption': caption, 'confidence': 'computed',
                })
    return relations


AUTHORSHIP_VERB = {
    'architect': 'Он построил',
    'engineer': 'Он спроектировал',
    'sculptor': 'Его работа',
}


def work_caption(work: wikidata.Work) -> str:
    return f'{AUTHORSHIP_VERB.get(work.authorship, "Его работа")}: {work.title}'


# --------------------------------------------------------------------------
# Оркестрация
# --------------------------------------------------------------------------

@dataclass
class Report:
    fetched: int = 0
    after_dedup: int = 0
    by_wikidata: int = 0
    by_matching: int = 0
    unresolved: int = 0
    persons: int = 0
    works: int = 0
    works_persons: int = 0
    links: int = 0
    relations: int = 0
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        pool = self.by_wikidata + self.by_matching
        share = f'{pool / self.after_dedup * 100:.0f}%' if self.after_dedup else '—'
        lines = [
            '',
            f'  Получено из OSM ................ {self.fetched}',
            f'  После дедупликации ............. {self.after_dedup}',
            '',
            f'  Персона из subject:wikidata .... {self.by_wikidata}   (2–4 мин на запись)',
            f'  Персона по тексту надписи ...... {self.by_matching}   (4–6 мин)',
            f'  Не сопоставлено ................ {self.unresolved}   (8–10 мин)',
            f'  Готово к быстрой проверке ...... {pool} из {self.after_dedup} ({share})',
            '',
            f'  Персон в базе .................. {self.persons}',
            f'  Построек с координатами ........ {self.works} у {self.works_persons} персон',
            f'  Ссылок на произведения ......... {self.links}',
            f'  Связей вычислено ............... {self.relations}',
        ]
        if self.after_dedup:
            hours = (self.by_wikidata * 3 + self.by_matching * 5 + self.unresolved * 9) / 60
            lines += ['', f'  Оценка работы редактора ........ {hours:.1f} ч на всё',
                      '  (по 20 записей за сессию, не больше — docs/06-content-plan.md)']
        lines += ['', *self.notes]
        return '\n'.join(lines)


def _person_row(person: wikidata.Person) -> dict:
    return {
        'wikidata_id': person.wikidata_id,
        'full_name': person.full_name,
        'name_normalized': fold(person.full_name),
        'surname': person.surname,
        'birth_year': person.birth_year,
        'death_year': person.death_year,
        'occupation': person.occupation,
        'article_url': person.article_url,
        'portrait_url': person.portrait_url,
    }


def _residence_years(parsed) -> tuple[int, int] | None:
    years = sorted(y for y in parsed.years if 1600 < y < 2030)
    if len(years) >= 2 and parsed.relation in (None, 'lived', 'worked'):
        return years[0], years[-1]
    return None


def run_import(conn, bbox, *, fetchers=None, search_limit=6) -> Report:
    """Полный проход импорта. Сетевые вызовы вынесены в `fetchers`,
    чтобы весь конвейер можно было прогнать на фикстурах без сети."""
    f = fetchers or {}
    fetch_osm = f.get('osm', osm.fetch)
    fetch_persons = f.get('persons', wikidata.fetch_persons)
    search_people = f.get('search', wikidata.search_people)
    fetch_works = f.get('works', wikidata.fetch_works)

    report = Report()
    plaques = fetch_osm(bbox)
    report.fetched = len(plaques)
    plaques = osm.deduplicate(plaques)
    report.after_dedup = len(plaques)

    # --- 1. Персоны, у которых привязка уже есть -------------------------
    linked_qids = {p.subject_wikidata for p in plaques if p.subject_wikidata}
    persons = fetch_persons(linked_qids) if linked_qids else {}

    # --- 2. Персоны, которых надо найти по тексту надписи (US-5.1d) ------
    pending = [p for p in plaques if not p.subject_wikidata and p.inscription]
    resolved: dict[str, tuple[wikidata.Person, float]] = {}
    for plaque in pending:
        parsed = parse_inscription(plaque.inscription)
        if not parsed.words:
            continue
        # Ищем по самым длинным словам надписи: фамилия почти всегда среди них
        query = ' '.join(sorted(parsed.words, key=len, reverse=True)[:3])
        qids = search_people(query, limit=search_limit)
        if not qids:
            continue
        candidates = fetch_persons(qids)
        persons.update(candidates)
        best, score, _ = wikidata.resolve(parsed.words, parsed.years,
                                          list(candidates.values()))
        if best:
            resolved[plaque.osm_id] = (best, score)

    # --- 3. Запись персон ------------------------------------------------
    person_ids: dict[str, int] = {}
    used = {p.subject_wikidata for p in plaques if p.subject_wikidata}
    used |= {person.wikidata_id for person, _ in resolved.values()}
    for qid in used:
        person = persons.get(qid)
        if person:
            person_ids[qid] = db.upsert(conn, 'person', 'wikidata_id', _person_row(person))
    report.persons = len(person_ids)

    # --- 4. Запись табличек ----------------------------------------------
    rows: list[PlaqueRow] = []
    for plaque in plaques:
        parsed = parse_inscription(plaque.inscription or '')
        qid, resolution, score = plaque.subject_wikidata, 'wikidata', None
        if not qid and plaque.osm_id in resolved:
            person, score = resolved[plaque.osm_id]
            qid, resolution = person.wikidata_id, 'matched'
        elif not qid:
            resolution = 'unresolved'

        person_id = person_ids.get(qid) if qid else None
        residence = _residence_years(parsed)
        plaque_id = db.upsert(conn, 'plaque', 'osm_id', {
            'osm_id': plaque.osm_id, 'person_id': person_id,
            'inscription': plaque.inscription, 'lat': plaque.lat, 'lon': plaque.lon,
            'relation_type': parsed.relation,
            'relation_years': f'{residence[0]}–{residence[1]}' if residence else None,
            'installed_year': plaque.installed_year,
            'resolution': resolution, 'match_score': score, 'status': 'draft',
        })
        if resolution == 'wikidata':
            report.by_wikidata += 1
        elif resolution == 'matched':
            report.by_matching += 1
        else:
            report.unresolved += 1

        if person_id:
            person = persons[qid]
            rows.append(PlaqueRow(
                plaque_id=plaque_id, person_id=person_id,
                lat=plaque.lat, lon=plaque.lon, surname=person.surname,
                residence_years=residence,
                life_years=(person.birth_year, person.death_year),
            ))
            if plaque.inscription:
                db.upsert(conn, 'source', 'url', {
                    'entity_type': 'plaque', 'entity_id': plaque_id,
                    'url': f'https://www.openstreetmap.org/{plaque.osm_id}',
                    'title': 'OpenStreetMap', 'license': 'ODbL',
                })

    # --- 5. Постройки ----------------------------------------------------
    works = fetch_works(list(person_ids)) if person_ids else []
    work_persons = set()
    for work in works:
        person_id = person_ids.get(work.person_wikidata_id)
        if not person_id:
            continue
        work_persons.add(person_id)
        work_id = db.upsert(conn, 'work', 'wikidata_id', {
            'wikidata_id': work.wikidata_id, 'person_id': person_id,
            'title': work.title, 'work_type': work.work_type,
            'authorship': work.authorship, 'lat': work.lat, 'lon': work.lon,
            'built_year': work.built_year, 'status': 'draft',
        })
        insert_relation(conn, {
            'from_type': 'person', 'from_id': person_id,
            'to_type': 'work', 'to_id': work_id,
            'relation_kind': 'work', 'caption': work_caption(work),
            'confidence': 'wikidata',
        })
    report.works, report.works_persons = len(works), len(work_persons)

    # --- 6. Ссылки на внешние произведения -------------------------------
    for qid, person_id in person_ids.items():
        for link in content_links_for(persons[qid]):
            db.upsert(conn, 'content_link', 'url', {'person_id': person_id, **link})
            report.links += 1

    # --- 7. Вычисляемые связи --------------------------------------------
    for rel in computed_relations(rows):
        insert_relation(conn, rel)
    report.relations = conn.execute('SELECT COUNT(*) FROM relation').fetchone()[0]

    conn.commit()
    if report.unresolved:
        report.notes.append(
            f'  {report.unresolved} записей без персоны: их разбирать вручную. '
            'Если доля велика — стоит поднять search_limit или ослабить порог '
            'wikidata.CONFIDENT и снова прогнать импорт.')
    return report
