# -*- coding: utf-8 -*-
"""Выгрузка мемориальных табличек из OpenStreetMap через Overpass API.

Данные под лицензией ODbL — атрибуция обязательна в приложении.
"""
from __future__ import annotations

from dataclasses import dataclass

OVERPASS_URL = 'https://overpass-api.de/api/interpreter'

# Берём только записи, у которых есть надпись или привязка к персоне.
# По выгрузке 22.08.2026 остальные 44% стоят редактору 20–25 минут каждая
# и в MVP не окупаются — см. spike/osm_count.md.
QUERY_TEMPLATE = '''
[out:json][timeout:180];
(
  nwr["memorial"="plaque"]["inscription"]({bbox});
  nwr["memorial"="plaque"]["subject:wikidata"]({bbox});
  nwr["memorial:type"="plaque"]["inscription"]({bbox});
  nwr["memorial:type"="plaque"]["subject:wikidata"]({bbox});
  nwr["historic"="memorial"]["inscription"]({bbox});
  nwr["historic"="memorial"]["subject:wikidata"]({bbox});
);
out center tags;
'''


@dataclass
class OsmPlaque:
    osm_id: str
    lat: float
    lon: float
    inscription: str | None
    subject_wikidata: str | None
    name: str | None
    address: str | None
    installed_year: int | None

    @property
    def has_person_link(self) -> bool:
        return bool(self.subject_wikidata)


def build_query(bbox: tuple[float, float, float, float]) -> str:
    """bbox — (юг, запад, север, восток)."""
    return QUERY_TEMPLATE.format(bbox=','.join(str(v) for v in bbox))


def parse_response(payload: dict) -> list[OsmPlaque]:
    """Разбор ответа Overpass. Вынесено отдельно, чтобы тестировать без сети."""
    plaques = []
    for el in payload.get('elements', []):
        if el.get('type') == 'count':
            continue
        tags = el.get('tags') or {}
        lat = el.get('lat') or (el.get('center') or {}).get('lat')
        lon = el.get('lon') or (el.get('center') or {}).get('lon')
        if lat is None or lon is None:
            continue

        street = tags.get('addr:street')
        house = tags.get('addr:housenumber')
        address = ' '.join(p for p in (street, house) if p) or None

        year = None
        raw_year = tags.get('start_date') or ''
        if raw_year[:4].isdigit():
            year = int(raw_year[:4])

        plaques.append(OsmPlaque(
            osm_id=f"{el['type']}/{el['id']}",
            lat=float(lat), lon=float(lon),
            inscription=tags.get('inscription'),
            subject_wikidata=tags.get('subject:wikidata'),
            name=tags.get('name'),
            address=address,
            installed_year=year,
        ))
    return plaques


def fetch(bbox, session=None) -> list[OsmPlaque]:
    """Единственное место, где ходим в сеть."""
    import requests
    session = session or requests.Session()
    resp = session.post(OVERPASS_URL, data={'data': build_query(bbox)}, timeout=300)
    resp.raise_for_status()
    return parse_response(resp.json())


def deduplicate(plaques: list[OsmPlaque], radius_m: float = 15.0) -> list[OsmPlaque]:
    """Один и тот же объект бывает нанесён дважды — точкой и контуром."""
    from .db import haversine_m

    kept: list[OsmPlaque] = []
    for p in plaques:
        twin = next(
            (k for k in kept
             if haversine_m(p.lat, p.lon, k.lat, k.lon) <= radius_m
             and (not p.inscription or not k.inscription
                  or p.inscription.strip() == k.inscription.strip())),
            None,
        )
        if twin is None:
            kept.append(p)
        # Из пары оставляем более информативную запись
        elif (p.subject_wikidata and not twin.subject_wikidata) or \
             (p.inscription and not twin.inscription):
            kept[kept.index(twin)] = p
    return kept
