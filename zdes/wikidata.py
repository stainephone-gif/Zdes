# -*- coding: utf-8 -*-
"""Обогащение данными Wikidata: персоны, их постройки, ссылки на статьи.

Лицензия Wikidata — CC0. Сетевой слой держим тонким, всю логику разбора и
ранжирования выносим в чистые функции, чтобы их можно было проверить тестами.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .matcher import similarity

SPARQL_URL = 'https://query.wikidata.org/sparql'
API_URL = 'https://www.wikidata.org/w/api.php'
USER_AGENT = 'Zdes/0.1 (memorial plaques app; contact via repository)'

POINT_RE = re.compile(r'Point\(([-\d.]+)\s+([-\d.]+)\)')


@dataclass
class Person:
    wikidata_id: str
    full_name: str
    birth_year: int | None = None
    death_year: int | None = None
    occupation: str | None = None
    article_url: str | None = None
    portrait_url: str | None = None

    @property
    def surname(self) -> str:
        """В русской Wikidata метка почти всегда «Имя Отчество Фамилия»."""
        parts = [p for p in self.full_name.replace(' ', ' ').split() if p]
        return parts[-1] if parts else self.full_name

    @property
    def years(self) -> list[int]:
        return [y for y in (self.birth_year, self.death_year) if y]


@dataclass
class Work:
    wikidata_id: str
    person_wikidata_id: str
    title: str
    authorship: str
    lat: float
    lon: float
    built_year: int | None = None
    work_type: str | None = None


PERSON_SPARQL = '''
SELECT ?p ?pLabel ?birth ?death ?occLabel ?article ?image WHERE {
  VALUES ?p { %s }
  OPTIONAL { ?p wdt:P569 ?birth. }
  OPTIONAL { ?p wdt:P570 ?death. }
  OPTIONAL { ?p wdt:P106 ?occ. }
  OPTIONAL { ?article schema:about ?p; schema:isPartOf <https://ru.wikipedia.org/>. }
  OPTIONAL { ?p wdt:P18 ?image. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
}
'''

WORKS_SPARQL = '''
SELECT ?p ?w ?wLabel ?coord ?built ?typeLabel ?role WHERE {
  VALUES ?p { %s }
  {  ?w wdt:P84  ?p. BIND("architect" AS ?role) }
  UNION
  {  ?w wdt:P631 ?p. BIND("engineer"  AS ?role) }
  UNION
  {  ?w wdt:P170 ?p. BIND("sculptor"  AS ?role) }
  ?w wdt:P625 ?coord.
  OPTIONAL { ?w wdt:P571 ?built. }
  OPTIONAL { ?w wdt:P31 ?type. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ru,en". }
}
'''


def _year(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r'(-?\d{1,4})-', value)
    return int(m.group(1)) if m and m.group(1).isdigit() else None


def _qid(uri: str) -> str:
    return uri.rsplit('/', 1)[-1]


def parse_persons(payload: dict) -> dict[str, Person]:
    """Разбор ответа SPARQL по персонам. Одна персона — несколько строк."""
    persons: dict[str, Person] = {}
    for row in payload.get('results', {}).get('bindings', []):
        qid = _qid(row['p']['value'])
        person = persons.get(qid)
        if person is None:
            person = Person(wikidata_id=qid, full_name=row.get('pLabel', {}).get('value', qid))
            persons[qid] = person
        person.birth_year = person.birth_year or _year(row.get('birth', {}).get('value'))
        person.death_year = person.death_year or _year(row.get('death', {}).get('value'))
        person.article_url = person.article_url or row.get('article', {}).get('value')
        person.portrait_url = person.portrait_url or row.get('image', {}).get('value')
        occ = row.get('occLabel', {}).get('value')
        if occ and not occ.startswith('Q'):
            existing = person.occupation.split(', ') if person.occupation else []
            if occ not in existing and len(existing) < 3:
                person.occupation = ', '.join(existing + [occ])
    return persons


def parse_works(payload: dict) -> list[Work]:
    works: list[Work] = []
    for row in payload.get('results', {}).get('bindings', []):
        point = POINT_RE.match(row.get('coord', {}).get('value', '') or '')
        if not point:
            continue
        lon, lat = float(point.group(1)), float(point.group(2))
        wtype = row.get('typeLabel', {}).get('value')
        works.append(Work(
            wikidata_id=_qid(row['w']['value']),
            person_wikidata_id=_qid(row['p']['value']),
            title=row.get('wLabel', {}).get('value', ''),
            authorship=row.get('role', {}).get('value', 'architect'),
            lat=lat, lon=lon,
            built_year=_year(row.get('built', {}).get('value')),
            work_type=wtype if wtype and not wtype.startswith('Q') else None,
        ))
    return works


# --------------------------------------------------------------------------
# Сопоставление персоны по тексту надписи — US-5.1d.
# Самая окупаемая часть импорта: переводит 560 записей из 8–10 минут в 4–6.
# --------------------------------------------------------------------------

# Порог осознанно высокий. Неверно предложенная персона стоит редактору
# исправления, но если предлагать слишком охотно, проверка станет формальной.
CONFIDENT = 0.78
W_NAME, W_YEARS = 0.65, 0.35


def score_candidate(words: list[str], years: list[int], cand: Person) -> float:
    """Насколько кандидат из Wikidata похож на то, что написано на табличке."""
    name = max((similarity(cand.surname, w) for w in words), default=0.0)
    cand_years = cand.years
    if years and cand_years:
        hits = len(set(years) & set(cand_years))
        # Годы на табличке есть, но не совпали ни одним — почти наверняка не он
        years_score = hits / len(cand_years) if hits else 0.0
    else:
        years_score = 0.5      # данных нет — не поощряем и не штрафуем
    return W_NAME * name + W_YEARS * years_score


def rank_candidates(words, years, candidates: list[Person]):
    scored = sorted(
        ((score_candidate(words, years, c), c) for c in candidates),
        key=lambda pair: pair[0], reverse=True,
    )
    return scored


def resolve(words, years, candidates: list[Person]):
    """Возвращает (персона|None, score, все кандидаты по убыванию)."""
    scored = rank_candidates(words, years, candidates)
    if not scored:
        return None, 0.0, []
    best_score, best = scored[0]
    return (best if best_score >= CONFIDENT else None), best_score, scored


# --------------------------------------------------------------------------
# Сетевой слой
# --------------------------------------------------------------------------

def _sparql(query: str, session=None) -> dict:
    import requests
    session = session or requests.Session()
    resp = session.get(
        SPARQL_URL,
        params={'query': query, 'format': 'json'},
        headers={'User-Agent': USER_AGENT, 'Accept': 'application/sparql-results+json'},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()


def _chunks(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_persons(qids, session=None) -> dict[str, Person]:
    result: dict[str, Person] = {}
    for chunk in _chunks(sorted(set(qids)), 150):
        values = ' '.join(f'wd:{q}' for q in chunk)
        result.update(parse_persons(_sparql(PERSON_SPARQL % values, session)))
    return result


def fetch_works(qids, session=None) -> list[Work]:
    works: list[Work] = []
    for chunk in _chunks(sorted(set(qids)), 100):
        values = ' '.join(f'wd:{q}' for q in chunk)
        works.extend(parse_works(_sparql(WORKS_SPARQL % values, session)))
    return works


def search_people(query: str, limit: int = 8, session=None) -> list[str]:
    """Поиск идентификаторов по строке имени. Возвращает список QID."""
    import requests
    session = session or requests.Session()
    resp = session.get(API_URL, params={
        'action': 'wbsearchentities', 'search': query, 'language': 'ru',
        'uselang': 'ru', 'type': 'item', 'limit': limit, 'format': 'json',
    }, headers={'User-Agent': USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return [item['id'] for item in resp.json().get('search', [])]
