# -*- coding: utf-8 -*-
"""HTTP-API приложения. Контракт — §8.4 ТЗ."""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from . import db
from .matcher import (THRESHOLD_AMBIGUOUS, THRESHOLD_AUTO, Candidate,
                      MIN_MARGIN, parse_inscription, rank)

DB_PATH = os.getenv('ZDES_DB', str(db.DEFAULT_DB))
OCR_ENGINE = os.getenv('ZDES_OCR', 'claude')
# Отладочный вход: позволяет прислать текст надписи вместо фотографии.
# Нужен, чтобы проверять сопоставление и клиент без камеры. В проде выключен.
ALLOW_TEXT_INPUT = os.getenv('ZDES_DEBUG_TEXT') == '1'

# Пороги и радиусы живут здесь, а не в приложении: их надо уметь менять
# после первых дней полевых данных, не выпуская новую версию (§6.4 ТЗ).
CONFIG = {
    'radius_m': float(os.getenv('ZDES_RADIUS_M', 75)),
    'radius_fallback_m': float(os.getenv('ZDES_RADIUS_FALLBACK_M', 150)),
    'min_candidates': 3,
    'nearby_radius_m': 500,
    'threshold_auto': THRESHOLD_AUTO,
    'threshold_ambiguous': THRESHOLD_AMBIGUOUS,
    'min_margin': MIN_MARGIN,
    'coverage_note': 'Пока мы знаем таблички только в нескольких кварталах центра Москвы',
}

app = FastAPI(title='Zdes API', version='0.1')


def conn():
    return db.connect(DB_PATH)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _plaque_brief(row, distance_m=None, person=None):
    out = {
        'plaque_id': row['id'],
        'inscription': row['inscription'],
        'lat': row['lat'], 'lon': row['lon'],
        'relation_type': row['relation_type'],
        'relation_years': row['relation_years'],
    }
    if distance_m is not None:
        out['distance_m'] = round(distance_m)
    if person:
        out['person'] = {
            'id': person['id'], 'full_name': person['full_name'],
            'years': _years_label(person),
            'occupation': person['occupation'],
        }
    return out


def _years_label(person):
    b, d = person['birth_year'], person['death_year']
    return f'{b or "?"}–{d or "?"}' if (b or d) else None


def _person_row(c, person_id):
    return c.execute('SELECT * FROM person WHERE id = ?', (person_id,)).fetchone()


# --------------------------------------------------------------------------

@app.get('/v1/config')
def get_config():
    return CONFIG


@app.get('/health')
def health():
    with conn() as c:
        published = c.execute("SELECT COUNT(*) FROM plaque WHERE status='published'").fetchone()[0]
        total = c.execute('SELECT COUNT(*) FROM plaque').fetchone()[0]
    return {'ok': True, 'plaques_published': published, 'plaques_total': total,
            'ocr_engine': OCR_ENGINE}


@app.get('/v1/nearby')
def nearby(lat: float, lon: float, radius: float = 500, limit: int = 100):
    radius = min(radius, 2000)
    with conn() as c:
        found = db.plaques_near(c, lat, lon, radius)[:limit]
        items = []
        for distance, row in found:
            person = _person_row(c, row['person_id']) if row['person_id'] else None
            items.append(_plaque_brief(row, distance, person))
    return {'items': items, 'radius_m': radius, 'coverage_note': CONFIG['coverage_note']}


@app.get('/v1/person/{person_id}')
def person_card(person_id: int, lat: float | None = None, lon: float | None = None):
    with conn() as c:
        person = _person_row(c, person_id)
        if not person:
            raise HTTPException(404, 'персона не найдена')

        works = []
        for w in c.execute("SELECT * FROM work WHERE person_id = ? AND status != 'archived'",
                           (person_id,)):
            item = {'id': w['id'], 'title': w['title'], 'work_type': w['work_type'],
                    'authorship': w['authorship'], 'lat': w['lat'], 'lon': w['lon'],
                    'built_year': w['built_year']}
            if lat is not None and lon is not None and w['lat']:
                item['distance_m'] = round(db.haversine_m(lat, lon, w['lat'], w['lon']))
            works.append(item)
        # Ближайшее — первым: смысл блока в том, чтобы дойти, а не прочитать
        works.sort(key=lambda w: w.get('distance_m', 10 ** 9))

        links = [dict(r) for r in c.execute(
            'SELECT id, type, title, url, provider FROM content_link '
            'WHERE person_id = ? AND is_alive = 1', (person_id,))]

        plaques = [_plaque_brief(r) for r in c.execute(
            'SELECT * FROM plaque WHERE person_id = ?', (person_id,))]

        relations = []
        for r in c.execute(
                'SELECT * FROM relation WHERE (from_type = ? AND from_id = ?) '
                'OR (from_type = ? AND from_id IN (SELECT id FROM plaque WHERE person_id = ?))',
                ('person', person_id, 'plaque', person_id)):
            relations.append({'kind': r['relation_kind'], 'caption': r['caption'],
                              'to_type': r['to_type'], 'to_id': r['to_id'],
                              'confidence': r['confidence']})

        sources = [dict(r) for r in c.execute(
            'SELECT url, title, license FROM source WHERE entity_type = ? AND entity_id = ?',
            ('person', person_id))]
        if person['article_url']:
            sources.append({'url': person['article_url'], 'title': 'Википедия',
                            'license': 'CC BY-SA'})

    return {
        'id': person['id'],
        'full_name': person['full_name'],
        'years': _years_label(person),
        'occupation': person['occupation'],
        'short_description': person['short_description'],
        'description_status': person['description_status'],
        'portrait_url': person['portrait_url'],
        'plaques': plaques,
        'works': works,
        'content_links': links,
        'relations': relations,
        'sources': sources,
    }


@app.get('/v1/search')
def search(q: str, limit: int = 20):
    if len(q.strip()) < 3:
        return {'items': []}
    with conn() as c:
        rows = c.execute(
            'SELECT id, full_name, birth_year, death_year, occupation FROM person '
            'WHERE full_name LIKE ? OR surname LIKE ? LIMIT ?',
            (f'%{q}%', f'%{q}%', limit)).fetchall()
    return {'items': [dict(r) for r in rows]}


@app.post('/v1/recognize')
async def recognize(
    image: UploadFile | None = File(None),
    text: str | None = Form(None),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    device_id: str = Form('anonymous'),
):
    started = time.time()

    if text is not None and ALLOW_TEXT_INPUT:
        ocr_text, engine_name = text, 'debug-text'
    elif image is not None:
        from .ocr import ENGINES

        engine = ENGINES.get(OCR_ENGINE)
        if engine is None:
            raise HTTPException(503, f'движок {OCR_ENGINE} не настроен')
        reason = engine.available()
        if reason:
            raise HTTPException(503, f'движок {OCR_ENGINE} недоступен: {reason}')

        payload = await image.read()
        if len(payload) > 8 * 1024 * 1024:
            raise HTTPException(413, 'изображение слишком большое')

        suffix = '.png' if image.filename and image.filename.endswith('.png') else '.jpg'
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(payload)
            tmp.flush()
            result = engine.read(tmp.name)
        if result.error:
            raise HTTPException(503, f'распознавание не удалось: {result.error}')
        ocr_text, engine_name = result.text, OCR_ENGINE
    else:
        raise HTTPException(400, 'нужна фотография')

    with conn() as c:
        # Гео-фильтр — основной источник точности. Без координат работаем
        # по всей базе: по модели это стоит около 3 п.п. точности.
        if lat is not None and lon is not None:
            radius = CONFIG['radius_m']
            found = db.plaques_near(c, lat, lon, radius)
            if len(found) < CONFIG['min_candidates']:
                radius = CONFIG['radius_fallback_m']
                found = db.plaques_near(c, lat, lon, radius)
        else:
            # Координат нет — работаем по всей базе. Расстояние ставим
            # нейтральное: нулевое означало бы «стоим вплотную ко всем сразу»
            # и завышало бы уверенность там, где мы как раз не уверены.
            radius = CONFIG['radius_fallback_m']
            neutral = radius / 2
            found = [(neutral, r) for r in c.execute(
                "SELECT * FROM plaque WHERE status='published'")]

        candidates, by_id = [], {}
        for distance, row in found:
            if not row['person_id']:
                continue
            person = _person_row(c, row['person_id'])
            candidates.append(Candidate(
                plaque_id=str(row['id']), surname=person['surname'] or person['full_name'],
                birth_year=person['birth_year'], death_year=person['death_year'],
                distance_m=distance,
            ))
            by_id[str(row['id'])] = (row, person, distance)

        status, scored = rank(ocr_text, candidates, radius_m=radius)
        items = []
        for score, cand in scored[:3]:
            row, person, distance = by_id[cand.plaque_id]
            item = _plaque_brief(row, distance, person)
            item['score'] = round(score, 3)
            items.append(item)

        c.execute(
            'INSERT INTO recognition_event (device_id_hash, created_at, lat, lon, ocr_text, '
            'engine, top_score, candidates, chosen_plaque_id, outcome) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)',
            (device_id, _now(), lat, lon, ocr_text, engine_name,
             items[0]['score'] if items else None, json.dumps(items, ensure_ascii=False),
             None, 'auto' if status == 'matched' else status))
        c.commit()

    return JSONResponse({
        'status': status,
        'ocr_text': ocr_text,
        'engine': engine_name,
        'latency_ms': int((time.time() - started) * 1000),
        'candidates': items,
        # Подсказку о покрытии показываем, когда не смогли опознать —
        # именно там пользователю нужно объяснение, а не пустой экран.
        'coverage_note': CONFIG['coverage_note'] if status == 'not_found' else None,
    })
