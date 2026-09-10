# Поиск по смыслу: сравниваем не буквы, а наборы чисел (эмбеддинги).
# Настоящую модель не зовём — числа для учебных фраз проставлены вручную
# по четырём осям: [про учёбу, про еду, про время работы, про технику].

import math

# --- НАСТРОЙКИ ---
SKOLKO_POKAZAT = 3        # сколько лучших результатов печатать

CHANKI = {
    "Кружок робототехники: вторник и четверг, 15:40, кабинет 204": [0.9, 0.0, 0.6, 0.9],
    "Кружок рисования: среда, 16:00, кабинет 112":                 [0.85, 0.0, 0.55, 0.0],
    "Столовая работает с 9:00 до 15:00":                           [0.05, 0.95, 0.6, 0.0],
    "В буфете продают пирожки и сок":                              [0.0, 0.9, 0.05, 0.0],
    "Библиотека открыта с 8:30 до 17:00":                          [0.4, 0.0, 0.6, 0.0],
}

VOPROSY = {
    # Ни одного общего слова с нужным чанком — поиск по словам тут бессилен.
    "когда занятия у робототехников":  [0.9, 0.0, 0.65, 0.85],
    "где можно перекусить":            [0.0, 0.92, 0.1, 0.0],
    "во сколько закрывается читальня": [0.35, 0.0, 0.7, 0.0],
}


def kosinusnaya_blizost(a, b):
    """Насколько два вектора смотрят в одну сторону: 1 — одинаково, 0 — не связаны."""
    skalyarnoe = sum(x * y for x, y in zip(a, b))       # перемножили и сложили
    dlina_a = math.sqrt(sum(x * x for x in a))          # длина первой стрелки
    dlina_b = math.sqrt(sum(y * y for y in b))          # длина второй стрелки
    return skalyarnoe / (dlina_a * dlina_b)


for vopros, vektor_voprosa in VOPROSY.items():
    print("=" * 60)
    print(f"ВОПРОС: {vopros}")
    print(f"его эмбеддинг: {vektor_voprosa}\n")

    rezultaty = []
    for chank, vektor_chanka in CHANKI.items():
        blizost = kosinusnaya_blizost(vektor_voprosa, vektor_chanka)
        rezultaty.append((blizost, chank))

    rezultaty.sort(reverse=True)

    for blizost, chank in rezultaty[:SKOLKO_POKAZAT]:
        print(f"  {blizost:.3f} | {chank}")
    print()
