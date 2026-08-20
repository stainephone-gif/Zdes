# -*- coding: utf-8 -*-
"""
Прогон эталонного набора фотографий через все доступные OCR-движки.

Мерим не «качество OCR» само по себе, а то, что нас реально волнует:
попали ли мы в верную персону из гео-отфильтрованного списка кандидатов.

    python3 spike/ocr_bench/bench.py --photos photos/ --truth ground_truth.csv
    python3 spike/ocr_bench/bench.py --photos photos/ --engines paddle,claude

Формат ground_truth.csv:
    file,surname,birth_year,death_year,lat,lon,condition
    IMG_001.jpg,Булгаков,1891,1940,55.7663,37.5936,день
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engines import ENGINES              # noqa: E402
from matcher import Candidate, rank      # noqa: E402


def load_truth(path):
    with open(path, encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def build_candidates(row, all_rows, n_candidates):
    """Имитируем гео-фильтр: верная персона + соседи по кварталу."""
    def to_cand(r, distance):
        return Candidate(
            plaque_id=r['file'],
            surname=r['surname'],
            birth_year=int(r['birth_year']) if r.get('birth_year') else None,
            death_year=int(r['death_year']) if r.get('death_year') else None,
            distance_m=distance,
        )

    others = [r for r in all_rows if r['file'] != row['file']]
    picked = random.sample(others, min(n_candidates - 1, len(others)))
    return [to_cand(row, random.uniform(0, 30))] + [
        to_cand(r, random.uniform(20, 75)) for r in picked
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--photos', required=True, help='папка с фотографиями')
    ap.add_argument('--truth', default='ground_truth.csv')
    ap.add_argument('--engines', default='', help='через запятую; по умолчанию все доступные')
    ap.add_argument('--candidates', type=int, default=6,
                    help='сколько табличек попадает в радиус гео-фильтра')
    ap.add_argument('--out', default='bench_results.csv')
    args = ap.parse_args()

    random.seed(42)
    truth = load_truth(args.truth)
    wanted = [e.strip() for e in args.engines.split(',') if e.strip()] or list(ENGINES)

    active = {}
    for name in wanted:
        engine = ENGINES.get(name)
        if engine is None:
            print(f'  пропуск {name}: нет такого движка')
            continue
        reason = engine.available()
        if reason:
            print(f'  пропуск {name}: {reason}')
            continue
        active[name] = engine

    if not active:
        print('\nНи один движок не доступен. Установите хотя бы один и повторите.')
        return 1

    print(f'\nДвижки: {", ".join(active)}   Фотографий: {len(truth)}   '
          f'Кандидатов в радиусе: {args.candidates}\n')

    rows = []
    for i, item in enumerate(truth, 1):
        path = os.path.join(args.photos, item['file'])
        if not os.path.exists(path):
            print(f'  нет файла: {path}')
            continue
        candidates = build_candidates(item, truth, args.candidates)
        for name, engine in active.items():
            res = engine.read(path)
            status, scored = rank(res.text, candidates)
            top = scored[0][1].surname if scored else ''
            rows.append({
                'file': item['file'],
                'condition': item.get('condition', ''),
                'engine': name,
                'status': status,
                'expected': item['surname'],
                'got': top,
                'correct': int(top == item['surname']),
                'top_score': round(scored[0][0], 3) if scored else 0.0,
                'in_top3': int(any(c.surname == item['surname'] for _, c in scored[:3])),
                'latency_ms': res.latency_ms,
                'cost_usd': round(res.cost_usd, 5),
                'error': res.error or '',
                'ocr_text': ' '.join(res.text.split())[:300],
            })
        print(f'  [{i}/{len(truth)}] {item["file"]}')

    with open(args.out, 'w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f'\nСырые результаты: {args.out}\n')
    header = (f'{"движок":<12}{"RSR":>8}{"top-3":>8}{"уверенно":>10}'
              f'{"ложных":>9}{"p50 мс":>9}{"p90 мс":>9}{"$/1000":>9}')
    print(header)
    print('-' * len(header))
    for name in active:
        sub = [r for r in rows if r['engine'] == name]
        if not sub:
            continue
        lat = sorted(r['latency_ms'] for r in sub)
        confident = [r for r in sub if r['status'] == 'matched']
        wrong = [r for r in confident if not r['correct']]
        print(f'{name:<12}'
              f'{sum(r["correct"] for r in sub) / len(sub) * 100:>7.1f}%'
              f'{sum(r["in_top3"] for r in sub) / len(sub) * 100:>7.1f}%'
              f'{len(confident) / len(sub) * 100:>9.1f}%'
              f'{(len(wrong) / len(confident) * 100 if confident else 0):>8.1f}%'
              f'{statistics.median(lat):>9.0f}'
              f'{lat[int(len(lat) * 0.9) - 1]:>9.0f}'
              f'{sum(r["cost_usd"] for r in sub) / len(sub) * 1000:>9.2f}')

    print('\nRSR       — доля фото, где верная персона оказалась первой')
    print('уверенно  — доля фото, где показали бы карточку сразу, без выбора')
    print('ложных    — из показанных сразу карточек оказались НЕ тем человеком')
    print('            (главный порог качества: не выше 2%)\n')

    conditions = sorted({r['condition'] for r in rows if r['condition']})
    if conditions:
        print(f'{"условие":<20}' + ''.join(f'{n:>12}' for n in active))
        print('-' * (20 + 12 * len(active)))
        for cond in conditions:
            line = f'{cond:<20}'
            for name in active:
                sub = [r for r in rows if r['condition'] == cond and r['engine'] == name]
                line += (f'{sum(r["correct"] for r in sub) / len(sub) * 100:>11.0f}%'
                         if sub else f'{"—":>12}')
            print(line)
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
