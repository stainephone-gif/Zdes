# -*- coding: utf-8 -*-
"""Регрессия на логику, которая решает, того ли человека мы показали.

Запуск:  python3 tests/test_pipeline.py    (или pytest, если установлен)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zdes import db, importer, osm, wikidata  # noqa: E402
from zdes.matcher import Candidate, parse_inscription, rank, similarity  # noqa: E402


def test_inscription_parsing():
    p = parse_inscription('ЗДЕСЬ С 1927 ПО 1940 ГОД ЖИЛ ПИСАТЕЛЬ МИХАИЛ БУЛГАКОВ')
    assert p.years == [1927, 1940]
    assert p.relation == 'lived'
    assert 'БУЛГАКОВ' in p.words
    assert 'ЖИЛ' not in p.words        # служебные слова отсеяны


def test_ocr_damage_survives_folding():
    """Цифра посреди фамилии не должна рвать её на два обрубка."""
    p = parse_inscription('ЗДЕСЬ ЖИЛ БУЛГ4КОВ')
    assert len(p.words) == 1, p.words
    assert similarity(p.words[0], 'Булгаков') > 0.8


def test_latin_lookalikes_folded():
    p = parse_inscription('ЖИЛ БУЛГAKOB')      # A, K, O, B — латиница
    assert similarity(p.words[0], 'Булгаков') > 0.8


def test_confident_match():
    cands = [
        Candidate('1', 'Булгаков', 1891, 1940, distance_m=12),
        Candidate('2', 'Прокофьев', 1891, 1953, distance_m=40),
        Candidate('3', 'Шухов', 1853, 1939, distance_m=55),
    ]
    status, scored = rank('В ЭТОМ ДОМЕ ЖИЛ БУЛГАКОВ М.А. 1891-1940', cands)
    assert status == 'matched'
    assert scored[0][1].surname == 'Булгаков'


def test_garbage_fails_safely():
    """Уверенно показать не того человека дороже, чем не показать никого."""
    cands = [Candidate('1', 'Булгаков', 1891, 1940, distance_m=12)]
    status, _ = rank('нечитаемый мусор ###', cands)
    assert status == 'not_found'


def test_person_resolution_from_inscription():
    people = [
        wikidata.Person('Q1', 'Михаил Афанасьевич Булгаков', 1891, 1940),
        wikidata.Person('Q2', 'Сергей Сергеевич Прокофьев', 1891, 1953),
    ]
    parsed = parse_inscription('ЗДЕСЬ С 1927 ПО 1940 ЖИЛ МИХАИЛ АФАНАСЬЕВИЧ БУЛГАКОВ')
    best, score, _ = wikidata.resolve(parsed.words, parsed.years, people)
    assert best is not None and best.wikidata_id == 'Q1'

    other = parse_inscription('ЗДЕСЬ ЖИЛ ИВАНОВ')
    assert wikidata.resolve(other.words, other.years, people)[0] is None


def test_links_match_occupation():
    """Пустая или неуместная ссылка хуже отсутствующей."""
    writer = wikidata.Person('Q1', 'Булгаков', occupation='писатель')
    engineer = wikidata.Person('Q2', 'Шухов', occupation='инженер')
    assert [l['type'] for l in importer.content_links_for(writer)] == ['book']
    assert importer.content_links_for(engineer) == []


def test_relation_captions_are_honest():
    """Соседство утверждаем только когда знаем годы проживания обоих."""
    rows = [
        importer.PlaqueRow(1, 10, 55.7400, 37.5900, 'Булгаков', (1927, 1940), (1891, 1940)),
        importer.PlaqueRow(2, 11, 55.7401, 37.5902, 'Мандельштам', (1930, 1934), (1891, 1938)),
        importer.PlaqueRow(3, 12, 55.7402, 37.5901, 'Шухов', None, (1853, 1939)),
        importer.PlaqueRow(4, 13, 55.8000, 37.7000, 'Далёкий', None, (1900, 1980)),
    ]
    captions = {(r['from_id'], r['to_id']): r['caption']
                for r in importer.computed_relations(rows)}
    assert captions[(1, 2)] == 'Жил в соседнем доме в те же годы'
    assert captions[(1, 3)] == 'Современник, его табличка совсем рядом'
    assert not any(4 in key for key in captions)   # далёкая табличка связей не даёт


def _fixture_fetchers():
    people = {
        'Q4085': wikidata.Person('Q4085', 'Михаил Афанасьевич Булгаков', 1891, 1940, 'писатель'),
        'Q5679': wikidata.Person('Q5679', 'Владимир Григорьевич Шухов', 1853, 1939, 'инженер'),
    }
    plaques = [
        osm.OsmPlaque('node/1', 55.7400, 37.5900,
                      'ЗДЕСЬ С 1927 ПО 1940 ЖИЛ МИХАИЛ БУЛГАКОВ', None, None, None, None),
        osm.OsmPlaque('node/2', 55.7402, 37.5901,
                      'ЗДЕСЬ ЖИЛ ИНЖЕНЕР ВЛАДИМИР ШУХОВ', None, None, None, None),
        osm.OsmPlaque('node/3', 55.7600, 37.6100, None, 'Q4085', None, None, None),
        osm.OsmPlaque('node/4', 55.7800, 37.6500, 'ПАМЯТИ ЗАЩИТНИКОВ', None, None, None, None),
    ]
    return plaques, {
        'osm': lambda bbox: list(plaques),
        'persons': lambda qids: {q: people[q] for q in qids if q in people},
        'search': lambda query, limit=6: list(people),
        'works': lambda qids: [wikidata.Work('Q900', 'Q5679', 'Шуховская башня',
                                             'engineer', 55.7189, 37.6114, 1922)],
    }


def test_import_pipeline_end_to_end():
    _, fetchers = _fixture_fetchers()
    conn = db.connect(':memory:')
    report = importer.run_import(conn, (55.73, 37.58, 55.79, 37.66), fetchers=fetchers)

    assert report.by_wikidata == 1
    assert report.by_matching == 2
    assert report.unresolved == 1          # «ПАМЯТИ ЗАЩИТНИКОВ» — не персоналия
    assert report.works == 1

    resolutions = dict(conn.execute('SELECT osm_id, resolution FROM plaque'))
    assert resolutions['node/1'] == 'matched'
    assert resolutions['node/3'] == 'wikidata'
    assert resolutions['node/4'] == 'unresolved'


def test_import_is_idempotent():
    _, fetchers = _fixture_fetchers()
    conn = db.connect(':memory:')
    importer.run_import(conn, (55.73, 37.58, 55.79, 37.66), fetchers=fetchers)
    counts = lambda: tuple(
        conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        for t in ('plaque', 'person', 'work', 'relation', 'content_link')
    )
    first = counts()
    importer.run_import(conn, (55.73, 37.58, 55.79, 37.66), fetchers=fetchers)
    assert counts() == first, 'повторный импорт не должен плодить дубли'


def test_osm_deduplication():
    """Один объект, нанесённый точкой и контуром, — одна запись."""
    plaques = osm.parse_response({'elements': [
        {'type': 'node', 'id': 1, 'lat': 55.74, 'lon': 37.59,
         'tags': {'inscription': 'ЗДЕСЬ ЖИЛ БУЛГАКОВ'}},
        {'type': 'way', 'id': 2, 'center': {'lat': 55.74001, 'lon': 37.59001},
         'tags': {'inscription': 'ЗДЕСЬ ЖИЛ БУЛГАКОВ', 'subject:wikidata': 'Q4085'}},
    ]})
    kept = osm.deduplicate(plaques)
    assert len(kept) == 1
    assert kept[0].subject_wikidata == 'Q4085', 'остаться должна более полная запись'


def test_geo_search():
    conn = db.connect(':memory:')
    conn.execute("INSERT INTO plaque (osm_id, lat, lon, status) VALUES ('a', 55.7500, 37.6000, 'published')")
    conn.execute("INSERT INTO plaque (osm_id, lat, lon, status) VALUES ('b', 55.7505, 37.6000, 'published')")
    conn.execute("INSERT INTO plaque (osm_id, lat, lon, status) VALUES ('c', 55.8000, 37.6000, 'published')")
    conn.execute("INSERT INTO plaque (osm_id, lat, lon, status) VALUES ('d', 55.7501, 37.6000, 'draft')")
    found = db.plaques_near(conn, 55.7500, 37.6000, 100)
    assert [r['osm_id'] for _, r in found] == ['a', 'b'], 'draft не показываем, далёкое не берём'


if __name__ == '__main__':
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith('test_') and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f'  ✓ {name}')
        except AssertionError as exc:
            failed += 1
            print(f'  ✗ {name}: {exc}')
    print(f'\n  {len(tests) - failed} из {len(tests)} прошло')
    sys.exit(1 if failed else 0)
