# -*- coding: utf-8 -*-
"""Доступ к базе. SQLite: на объёме в сотни записей этого достаточно."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name('schema.sql')
DEFAULT_DB = Path(__file__).resolve().parent.parent / 'data' / 'zdes.sqlite3'


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text(encoding='utf-8'))
    return conn


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние в метрах. Для наших дистанций точности с запасом."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bbox_around(lat: float, lon: float, radius_m: float):
    """Грубый прямоугольник для предфильтра в SQL — дешевле, чем считать всё."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.01, math.cos(math.radians(lat))))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def plaques_near(conn, lat, lon, radius_m, only_published=True):
    """Таблички в радиусе, отсортированные по расстоянию."""
    lat0, lat1, lon0, lon1 = bbox_around(lat, lon, radius_m)
    sql = ('SELECT * FROM plaque WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?')
    args = [lat0, lat1, lon0, lon1]
    if only_published:
        sql += " AND status = 'published'"
    rows = conn.execute(sql, args).fetchall()
    out = []
    for row in rows:
        d = haversine_m(lat, lon, row['lat'], row['lon'])
        if d <= radius_m:
            out.append((d, row))
    out.sort(key=lambda p: p[0])
    return out


def upsert(conn, table: str, unique_column: str, values: dict) -> int:
    """Вставляет или обновляет запись по уникальному полю, возвращает id."""
    existing = conn.execute(
        f'SELECT id FROM {table} WHERE {unique_column} = ?',
        (values[unique_column],),
    ).fetchone()
    if existing:
        fields = [k for k in values if k != unique_column and values[k] is not None]
        if fields:
            conn.execute(
                f'UPDATE {table} SET {", ".join(f"{f} = ?" for f in fields)} WHERE id = ?',
                [values[f] for f in fields] + [existing['id']],
            )
        return existing['id']
    columns = list(values)
    cur = conn.execute(
        f'INSERT INTO {table} ({", ".join(columns)}) '
        f'VALUES ({", ".join("?" for _ in columns)})',
        [values[c] for c in columns],
    )
    return cur.lastrowid
