# -*- coding: utf-8 -*-
"""
Нормализация и сопоставление ФИО с мемориальной таблички.

Этот модуль — не только для спайка: та же логика идёт в продакшн-сервис.
Задача: по «грязному» тексту с OCR и списку гео-кандидатов выбрать одну персону.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Символы, которые OCR регулярно путает на камне и латуни. Приводим каждую
# группу к одному представителю, чтобы «БУЛГ4КОВ» и «БУЛГАКОВ» совпали.
FOLD_GROUPS = ['ОО0', 'ЕЁЕ', 'ЗЗ3', 'ВВ8', 'ЧЧ4', 'ББ6', 'ИЙ', 'ШЩ', 'ЬЫ']
FOLD = {ch: group[0] for group in FOLD_GROUPS for ch in group}

YEAR_RE = re.compile(r'\b(1[6-9]\d{2}|20[0-2]\d)\b')

# OCR сплошь и рядом отдаёт цифру вместо буквы и латиницу вместо кириллицы.
# Приводим их обратно ДО того, как разбиваем текст на слова, иначе одна
# ошибка посреди фамилии рвёт её на два обрубка.
DIGIT_TO_LETTER = str.maketrans('0346819', 'ОЗЧБВТЯ')
LATIN_TO_CYR = str.maketrans('ABCEHKMOPTXY', 'АВСЕНКМОРТХУ')

# Слова-связки на табличках: помогают понять тип связи с домом
RELATION_MARKERS = {
    'lived': ('ЖИЛ', 'ЖИЛА', 'ПРОЖИВАЛ', 'ПРОЖИВАЛА'),
    'worked': ('РАБОТАЛ', 'РАБОТАЛА', 'ТРУДИЛСЯ'),
    'born': ('РОДИЛСЯ', 'РОДИЛАСЬ'),
    'died': ('УМЕР', 'УМЕРЛА', 'СКОНЧАЛСЯ', 'ПОГИБ', 'ПОГИБЛА'),
}

# Служебные слова, которые не являются фамилией
STOPWORDS = {
    'ЗДЕСЬ', 'ДОМЕ', 'ЭТОМ', 'ГОДУ', 'ГОДЫ', 'ГОДА', 'ГОД', 'ПО', 'С', 'В',
    'ЖИЛ', 'ЖИЛА', 'РАБОТАЛ', 'РАБОТАЛА', 'РОДИЛСЯ', 'РОДИЛАСЬ', 'УМЕР',
    'УМЕРЛА', 'ПОГИБ', 'ВЫДАЮЩИЙСЯ', 'ИЗВЕСТНЫЙ', 'СОВЕТСКИЙ', 'РУССКИЙ',
    'ПАМЯТИ', 'ПАМЯТЬ', 'ПИСАТЕЛЬ', 'ПОЭТ', 'КОМПОЗИТОР', 'АКАДЕМИК',
    'ПРОФЕССОР', 'АРХИТЕКТОР', 'АКТЁР', 'АКТЕР', 'РЕЖИССЁР', 'РЕЖИССЕР',
}


def fold(s: str) -> str:
    """Приводит строку к устойчивому к ошибкам OCR виду."""
    s = s.upper().replace('Ё', 'Е')
    s = re.sub(r'[^А-ЯA-Z0-9]', '', s)
    return ''.join(FOLD.get(ch, ch) for ch in s)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    a, b = fold(a), fold(b)
    m = max(len(a), len(b))
    return 1.0 - levenshtein(a, b) / m if m else 0.0


def best_substring_similarity(needle: str, haystack_words: list[str]) -> float:
    """Ищем фамилию кандидата среди всех слов, прочитанных с таблички."""
    return max((similarity(needle, w) for w in haystack_words), default=0.0)


@dataclass
class Parsed:
    words: list[str]
    years: list[int]
    relation: str | None


def parse_inscription(text: str) -> Parsed:
    """Достаёт из сырого текста OCR слова-кандидаты на фамилию, годы и связку."""
    upper = text.upper().replace('Ё', 'Е')

    # Годы вынимаем первыми — иначе следующий шаг превратит их в буквы.
    years = [int(y) for y in YEAR_RE.findall(upper)]
    without_years = YEAR_RE.sub(' ', upper)
    cleaned = without_years.translate(DIGIT_TO_LETTER).translate(LATIN_TO_CYR)

    words = [w for w in re.findall(r'[А-Я]{3,}', cleaned) if w not in STOPWORDS]
    relation = next(
        (kind for kind, markers in RELATION_MARKERS.items()
         if any(m in upper for m in markers)),
        None,
    )
    return Parsed(words=words, years=years, relation=relation)


@dataclass
class Candidate:
    plaque_id: str
    surname: str
    birth_year: int | None = None
    death_year: int | None = None
    distance_m: float = 0.0


# Веса подобраны так, чтобы фамилия решала, а гео и годы подтверждали.
W_NAME, W_GEO, W_YEARS = 0.60, 0.20, 0.20

# Пороги. В продакшне живут в серверном конфиге и меняются без релиза.
THRESHOLD_AUTO = 0.72       # выше — показываем карточку сразу
THRESHOLD_AMBIGUOUS = 0.45  # выше — показываем список кандидатов
MIN_MARGIN = 0.10           # минимальный отрыв от второго кандидата


def score(parsed: Parsed, cand: Candidate, radius_m: float = 75.0) -> float:
    name = best_substring_similarity(cand.surname, parsed.words)
    geo = max(0.0, 1.0 - cand.distance_m / radius_m)
    cand_years = [y for y in (cand.birth_year, cand.death_year) if y]
    if parsed.years and cand_years:
        years = len(set(parsed.years) & set(cand_years)) / len(cand_years)
    else:
        years = 0.5  # нет данных — не штрафуем и не поощряем
    return W_NAME * name + W_GEO * geo + W_YEARS * years


def rank(text: str, candidates: list[Candidate], radius_m: float = 75.0):
    """Возвращает (status, отсортированный список (score, candidate))."""
    parsed = parse_inscription(text)
    scored = sorted(
        ((score(parsed, c, radius_m), c) for c in candidates),
        key=lambda p: p[0],
        reverse=True,
    )
    if not scored:
        return 'not_found', []
    top = scored[0][0]
    margin = top - scored[1][0] if len(scored) > 1 else 1.0
    if top >= THRESHOLD_AUTO and margin >= MIN_MARGIN:
        return 'matched', scored
    if top >= THRESHOLD_AMBIGUOUS:
        return 'ambiguous', scored[:3]
    return 'not_found', scored[:3]
