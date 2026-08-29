#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Демо-база из нескольких записей — чтобы поднять приложение до того,
как пройдёт настоящий импорт.

    python3 tools/seed_demo.py --db data/demo.sqlite3
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataclasses import replace  # noqa: E402

from zdes import db, importer, osm, wikidata  # noqa: E402

PEOPLE = {
    'Q4085': wikidata.Person('Q4085', 'Михаил Афанасьевич Булгаков', 1891, 1940,
                             'писатель, драматург', 'https://ru.wikipedia.org/wiki/Булгаков,_Михаил_Афанасьевич'),
    'Q5679': wikidata.Person('Q5679', 'Владимир Григорьевич Шухов', 1853, 1939,
                             'инженер, архитектор', 'https://ru.wikipedia.org/wiki/Шухов,_Владимир_Григорьевич'),
    'Q7328': wikidata.Person('Q7328', 'Сергей Сергеевич Прокофьев', 1891, 1953,
                             'композитор', 'https://ru.wikipedia.org/wiki/Прокофьев,_Сергей_Сергеевич'),
    'Q8047': wikidata.Person('Q8047', 'Константин Степанович Мельников', 1890, 1974,
                             'архитектор', 'https://ru.wikipedia.org/wiki/Мельников,_Константин_Степанович'),
}

PLAQUES = [
    osm.OsmPlaque('demo/1', 55.76624, 37.59364,
                  'В ЭТОМ ДОМЕ С 1921 ПО 1924 ГОД ЖИЛ ПИСАТЕЛЬ МИХАИЛ АФАНАСЬЕВИЧ БУЛГАКОВ',
                  'Q4085', None, 'Большая Садовая 10', 1990),
    osm.OsmPlaque('demo/2', 55.76701, 37.59512,
                  'ЗДЕСЬ С 1890 ПО 1939 ГОД ЖИЛ ИНЖЕНЕР ВЛАДИМИР ГРИГОРЬЕВИЧ ШУХОВ',
                  None, None, 'Малая Бронная 4', None),
    osm.OsmPlaque('demo/3', 55.75921, 37.60455,
                  'В ЭТОМ ДОМЕ С 1936 ПО 1953 ГОД ЖИЛ КОМПОЗИТОР СЕРГЕЙ СЕРГЕЕВИЧ ПРОКОФЬЕВ',
                  'Q7328', None, 'Камергерский переулок 6', 1963),
    osm.OsmPlaque('demo/4', 55.75088, 37.58817,
                  'ЗДЕСЬ ЖИЛ И РАБОТАЛ АРХИТЕКТОР КОНСТАНТИН СТЕПАНОВИЧ МЕЛЬНИКОВ',
                  None, None, 'Кривоарбатский переулок 10', None),
    osm.OsmPlaque('demo/5', 55.75102, 37.58790, 'ПАМЯТИ ЗАЩИТНИКОВ ГОРОДА',
                  None, None, None, None),
]

WORKS = [
    wikidata.Work('Q1001', 'Q5679', 'Шуховская башня', 'engineer', 55.71889, 37.61139, 1922, 'башня'),
    wikidata.Work('Q1002', 'Q5679', 'Дебаркадер Киевского вокзала', 'engineer', 55.74306, 37.56583, 1918, 'вокзал'),
    wikidata.Work('Q1003', 'Q8047', 'Дом Мельникова', 'architect', 55.75083, 37.58806, 1929, 'жилой дом'),
    wikidata.Work('Q1004', 'Q8047', 'Клуб имени Русакова', 'architect', 55.78889, 37.68194, 1929, 'клуб'),
]

DESCRIPTIONS = {
    'Q4085': 'Автор «Мастера и Маргариты», «Белой гвардии» и «Собачьего сердца». '
             'В квартире 50 на Большой Садовой прожил три года — этот адрес стал '
             '«нехорошей квартирой» романа.',
    'Q5679': 'Инженер, придумавший гиперболоидные конструкции и сетчатые оболочки. '
             'Его перекрытия держат крыши ГУМа, Пушкинского музея и Киевского вокзала.',
    'Q7328': 'Композитор, автор «Ромео и Джульетты», «Пети и волка», семи симфоний. '
             'Вернулся в СССР в 1936 году и последние годы жил в этом доме.',
    'Q8047': 'Архитектор-авангардист. Собственный дом из двух врезанных друг в друга '
             'цилиндров с шестигранными окнами построил себе сам в 1929 году.',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/demo.sqlite3')
    ap.add_argument('--keep-draft', action='store_true',
                    help='не публиковать записи — как после настоящего импорта')
    ap.add_argument('--here', metavar='ШИРОТА,ДОЛГОТА',
                    help='разложить демо-таблички вокруг указанной точки — чтобы '
                         'проверять приложение не в центре Москвы, а там, где вы есть')
    args = ap.parse_args()

    plaques = list(PLAQUES)
    if args.here:
        lat0, lon0 = (float(v) for v in args.here.split(','))
        # Сохраняем взаимное расположение табличек, переносим их центр к вам:
        # иначе связи «в соседнем доме» перестанут быть правдой
        clat = sum(p.lat for p in plaques) / len(plaques)
        clon = sum(p.lon for p in plaques) / len(plaques)
        plaques = [replace(p, lat=p.lat - clat + lat0, lon=p.lon - clon + lon0)
                   for p in plaques]
        print(f'\n  Таблички перенесены к точке {lat0}, {lon0}')

    path = Path(args.db)
    if path.exists():
        path.unlink()
    conn = db.connect(path)

    fetchers = {
        'osm': lambda bbox: plaques,
        'persons': lambda qids: {q: PEOPLE[q] for q in qids if q in PEOPLE},
        'search': lambda query, limit=6: list(PEOPLE),
        'works': lambda qids: list(WORKS),
    }
    report = importer.run_import(conn, (55.74, 37.57, 55.78, 37.62), fetchers=fetchers)
    print(report.render())

    for qid, text in DESCRIPTIONS.items():
        conn.execute("UPDATE person SET short_description = ?, description_status = 'verified' "
                     'WHERE wikidata_id = ?', (text, qid))
    if not args.keep_draft:
        conn.execute("UPDATE plaque SET status = 'published' WHERE person_id IS NOT NULL")
        conn.execute("UPDATE work SET status = 'published'")
        conn.execute("UPDATE relation SET status = 'published'")
    conn.commit()

    published = conn.execute("SELECT COUNT(*) FROM plaque WHERE status='published'").fetchone()[0]
    print(f'\n  Демо-база готова: {path}, опубликовано {published} табличек.')
    print(f'  Запуск:  ZDES_DB={path} uvicorn zdes.api:app --host 0.0.0.0 --port 8000')
    first = conn.execute("SELECT lat, lon FROM plaque WHERE status='published' "
                         'ORDER BY id LIMIT 1').fetchone()
    if first:
        print(f'  Координаты для проверки (эмулятор → Extended controls → Location):'
              f'\n    широта {first[0]}   долгота {first[1]}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
