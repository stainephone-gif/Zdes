#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Импорт табличек в базу.

    python3 tools/import_cli.py --corridor prechistenka
    python3 tools/import_cli.py --bbox 55.735,37.585,55.750,37.605
    python3 tools/import_cli.py --corridor all --db data/zdes.sqlite3

Коридоры-кандидаты описаны ниже. Рамки ориентировочные — уточните по карте
после того, как сравните их по числу записей (spike/osm_count.md).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zdes import db, importer  # noqa: E402

CORRIDORS = {
    'prechistenka': ((55.735, 37.585, 55.750, 37.605), 'Пречистенка — Остоженка — Гоголевский'),
    'arbat':        ((55.746, 37.578, 55.760, 37.605), 'Арбат — Поварская — Никитская'),
    'chistye':      ((55.756, 37.630, 55.768, 37.652), 'Чистые пруды — Мясницкая — Покровка'),
    'all':          ((55.720, 37.540, 55.800, 37.690), 'Весь центр'),
}


def main():
    ap = argparse.ArgumentParser(description='Импорт мемориальных табличек из OSM')
    ap.add_argument('--corridor', choices=sorted(CORRIDORS), help='именованный коридор')
    ap.add_argument('--bbox', help='юг,запад,север,восток — вместо --corridor')
    ap.add_argument('--db', default=str(db.DEFAULT_DB))
    ap.add_argument('--search-limit', type=int, default=6,
                    help='сколько кандидатов запрашивать у Wikidata на одну надпись')
    args = ap.parse_args()

    if args.bbox:
        bbox = tuple(float(v) for v in args.bbox.split(','))
        title = f'bbox {args.bbox}'
    elif args.corridor:
        bbox, title = CORRIDORS[args.corridor]
    else:
        ap.error('укажите --corridor или --bbox')

    print(f'\nИмпорт: {title}\n  bbox {bbox}\n  база {args.db}')
    print('  Overpass и Wikidata отвечают небыстро, на весь центр это несколько минут.')

    conn = db.connect(args.db)
    report = importer.run_import(conn, bbox, search_limit=args.search_limit)
    print(report.render())
    print(f'\n  Готово. Все записи со статусом draft — публиковать после проверки.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
