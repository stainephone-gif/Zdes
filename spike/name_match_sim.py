# -*- coding: utf-8 -*-
"""
Симуляция: насколько точным должен быть OCR, чтобы приложение выбрало
верную персону из гео-отфильтрованного списка кандидатов.

Мы НЕ показываем пользователю результат OCR. Мы используем его только чтобы
выбрать одну запись из заранее проверенного списка. Значит вопрос не
"прочитал ли OCR текст правильно", а "хватает ли прочитанного, чтобы
отличить нужную фамилию от остальных кандидатов рядом".

Запуск:  python3 spike/name_match_sim.py
"""
import random, statistics

random.seed(20260820)

SURNAMES = """
Булгаков Прокофьев Шостакович Маяковский Есенин Цветаева Пастернак Ахматова
Чехов Толстой Гоголь Скрябин Рахманинов Врубель Левитан Станиславский
Немирович-Данченко Вахтангов Мейерхольд Эйзенштейн Королёв Туполев Курчатов
Вавилов Ландау Капица Тимирязев Жуковский Менделеев Пирогов Склифосовский
Бурденко Ушаков Нахимов Рокоссовский Василевский Гагарин Циолковский Шухов
Мельников Щусев Жолтовский Фомин Казаков Баженов Шехтель Кекушев Клейн Иофан
Гиляровский Паустовский Платонов Олеша Багрицкий Светлов Твардовский Симонов
Фадеев Катаев Ильф Петров Зощенко Мандельштам Хлебников Брюсов Белый Куприн
Бунин Андреев Короленко Островский Тургенев Некрасов Тютчев Фет Аксаков
Сеченов Павлов Мечников Обручев Ферсман Зелинский Несмеянов Келдыш Лаврентьев
Харитон Зельдович Тамм Черенков Басов Прохоров Семёнов Иоффе Кржижановский
Уланова Плисецкая Лемешев Козловский Нежданова Собинов Шаляпин Ойстрах Гилельс
Рихтер Ростропович Хачатурян Шнитке Свиридов Дунаевский Утёсов Райкин Миронов
Даль Высоцкий Тарковский Шукшин Ромм Пырьев Александров Довженко Козинцев
""".split()

# Визуально похожие символы — то, на чём реально ошибается OCR по граниту и латуни
CONFUSE = {
    'О': 'ОС0', 'С': 'СОЕ', 'Е': 'ЕЁСВ', 'Ё': 'ЕЁ', 'З': 'ЗЭ3', 'Э': 'ЭЗ',
    'В': 'ВЫ8Б', 'Б': 'БВЬ6', 'Ь': 'ЬЫБ', 'Ы': 'ЫЬВ', 'И': 'ИНЙ', 'Й': 'ЙИ',
    'Н': 'НИП', 'П': 'ПЛГН', 'Л': 'ЛПАД', 'А': 'АДЛ', 'Д': 'ДАЛ', 'Г': 'ГТП',
    'Т': 'ТГ', 'Ш': 'ШЩ', 'Щ': 'ЩШ', 'Ц': 'ЦЩ', 'Ч': 'Ч4У', 'У': 'УЧ',
    'Ж': 'ЖК', 'К': 'КЖ', 'М': 'МН', 'Ф': 'ФР', 'Р': 'РФ', 'Х': 'ХЖ',
    'Я': 'ЯR', 'Ю': 'ЮО',
}


def corrupt(s, rate):
    """Портим строку так, как это делает OCR: замена похожим, пропуск, вставка."""
    out = []
    for ch in s.upper():
        r = random.random()
        if r > rate:
            out.append(ch)
        elif r < rate * 0.60:                       # замена похожим символом
            out.append(random.choice(CONFUSE.get(ch, ch)))
        elif r < rate * 0.85:                       # буква сколота / не прочитана
            pass
        else:                                       # шум: лишний символ
            out.append(ch)
            out.append(random.choice('ОАЕИНТ.-'))
    return ''.join(out)


def lev(a, b):
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


def sim(a, b):
    a, b = a.upper(), b.upper()
    m = max(len(a), len(b))
    return 1.0 - lev(a, b) / m if m else 0.0


def trial(candidates_n, rate, use_years, pool):
    target = random.choice(pool)
    others = random.sample([s for s in pool if s != target], candidates_n - 1)
    candidates = [target] + others
    t_year = random.randint(1850, 1950)
    years = {target: t_year}
    for o in others:
        years[o] = random.randint(1850, 1950)

    read_name = corrupt(target, rate)
    read_year = str(t_year) if random.random() > rate * 0.5 else corrupt(str(t_year), rate)

    scored = []
    for c in candidates:
        s = sim(read_name, c)
        if use_years:
            s = 0.80 * s + 0.20 * sim(read_year, str(years[c]))
        scored.append((s, c))
    scored.sort(reverse=True)

    best_s, best_c = scored[0]
    margin = best_s - scored[1][0] if len(scored) > 1 else 1.0
    return best_c == target, best_s, margin


def run(candidates_n, rate, use_years, pool, n=4000):
    ok = 0
    confident_wrong = 0
    confident = 0
    margins = []
    for _ in range(n):
        correct, score, margin = trial(candidates_n, rate, use_years, pool)
        ok += correct
        # "уверенный" ответ: высокий скор И заметный отрыв от второго кандидата
        if score >= 0.62 and margin >= 0.12:
            confident += 1
            if not correct:
                confident_wrong += 1
        margins.append(margin)
    return {
        'top1': ok / n,
        'confident_share': confident / n,
        'fpr': confident_wrong / confident if confident else 0.0,
        'margin': statistics.mean(margins),
    }


# Расширяем пул до размера "все таблички Москвы", чтобы честно посчитать вариант без гео
BIG_POOL = list(SURNAMES)
while len(BIG_POOL) < 800:
    BIG_POOL.append(random.choice(SURNAMES) + random.choice('ов ин ский ко ев ых'.split()))

RATES = [0.10, 0.20, 0.30, 0.40, 0.50]
SETS = [3, 5, 10, 50, 500]

results = {}
for k in SETS:
    pool = SURNAMES if k <= len(SURNAMES) else BIG_POOL
    n = 3000 if k <= 50 else 500
    for r in RATES:
        results[(k, r, False)] = run(k, r, False, pool, n)
        results[(k, r, True)] = run(k, r, True, pool, n)


def table(title, note, key, years):
    print(f'\n=== {title} ' + '=' * max(0, 66 - len(title)))
    print(note + '\n')
    print('кандидатов |' + ''.join(f'  ошибок OCR {int(r*100)}% ' for r in RATES))
    for k in SETS:
        print(f'{k:>10} |' + ''.join(
            f'{results[(k, r, years)][key] * 100:>16.1f}%' for r in RATES))


table('Только фамилия, без годов', 'Доля верных распознаваний в топ-1', 'top1', False)
table('Фамилия + годы жизни', 'Доля верных распознаваний в топ-1', 'top1', True)
table('Ложные срабатывания',
      'Уверенно показали НЕ того человека (score>=0.62, отрыв>=0.12) — самая опасная ошибка',
      'fpr', True)
print()
