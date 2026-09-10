# Крошечная "языковая модель": учится на нескольких фразах и генерирует текст.
# Показывает, как температура меняет предсказуемость ответа.

import random

# --- НАСТРОЙКИ ---
OBUCHAYUSHCHIY_TEKST = """
кот сидит на окне
кот сидит на диване
кот спит на окне
кот смотрит на птиц
пёс сидит на коврике
пёс спит на коврике
"""

PERVOE_SLOVO = "кот"
DLINA_OTVETA = 5                    # сколько слов сгенерировать
TEMPERATURY = [0.1, 1.0, 2.0]       # какие температуры сравнить
SKOLKO_POPYTOK = 3                  # сколько раз повторить для каждой температуры


def sobrat_statistiku(text):
    """Считает, какое слово сколько раз встречалось после каждого слова."""
    statistika = {}
    for stroka in text.strip().split("\n"):
        slova = stroka.split()
        for i in range(len(slova) - 1):
            tekushchee, sleduyushchee = slova[i], slova[i + 1]
            statistika.setdefault(tekushchee, {})
            statistika[tekushchee][sleduyushchee] = statistika[tekushchee].get(sleduyushchee, 0) + 1
    return statistika


def vybrat_sleduyushchee(varianty, temperatura):
    """Выбирает следующее слово с учётом температуры.

    Низкая температура -> редкие варианты почти не выпадают.
    Высокая температура -> шансы выравниваются, выбор непредсказуемее.
    """
    slova = list(varianty.keys())
    # Возводим частоту в степень 1/температура: это и есть "перемешивание шариков".
    vesa = [varianty[s] ** (1 / temperatura) for s in slova]
    return random.choices(slova, weights=vesa)[0]


def sgenerirovat(statistika, pervoe_slovo, dlina, temperatura):
    otvet = [pervoe_slovo]
    tekushchee = pervoe_slovo
    for _ in range(dlina - 1):
        if tekushchee not in statistika:
            break                       # продолжения не нашлось — заканчиваем
        tekushchee = vybrat_sleduyushchee(statistika[tekushchee], temperatura)
        otvet.append(tekushchee)
    return " ".join(otvet)


statistika = sobrat_statistiku(OBUCHAYUSHCHIY_TEKST)

print("Что модель выучила:")
for slovo, varianty in statistika.items():
    print(f"  после {slovo!r}: {varianty}")
print()

for temperatura in TEMPERATURY:
    print(f"--- температура {temperatura} ---")
    for _ in range(SKOLKO_POPYTOK):
        print("  " + sgenerirovat(statistika, PERVOE_SLOVO, DLINA_OTVETA, temperatura))
    print()
