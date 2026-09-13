# Большое окно или RAG? Один вопрос к документам разной длины, факт спрятан
# в начале, середине или конце. Считаем цену и проверяем, найден ли ответ.
# Заглушка модели ведёт себя, как описывают исследования длинного контекста:
# в очень длинном тексте факт из середины теряется чаще, чем из начала или конца.

import re

# --- НАСТРОЙКИ ---
OKNO = 128_000                 # контекстное окно модели, токенов
PORG_SEREDINY = 20_000         # с какой длины документа модель начинает терять середину
CENA_VHODA = 0.30              # $ за 1 млн входных токенов
KUSKOV_V_RAG = 3               # сколько кусков кладёт в запрос RAG
VOPROSOV_V_DEN = 500           # сколько раз в день задают вопросы по этому документу

FAKT = "Пропуск в спортзал выдаёт завуч Ольга Петровна в кабинете 115."
VOPROS = "Кто выдаёт пропуск в спортзал?"
VOPROS_INACHE = "У кого получить разрешение ходить на тренировки?"   # те же смысл, другие слова

ZAPOLNITEL = "Пункт {n}. Ученики соблюдают порядок в коридорах и бережно относятся к имуществу школы."


def tokeny(tekst):
    return len(tekst) // 2


def sdelat_dokument(abzacev, gde):
    abzacy = [ZAPOLNITEL.format(n=i + 1) for i in range(abzacev)]
    mesto = {"начало": 0, "середина": abzacev // 2, "конец": abzacev - 1}[gde]
    abzacy[mesto] = FAKT
    return abzacy, mesto / max(1, abzacev - 1)


def zaglushka_modeli(kontekst, polozhenie_fakta):
    """Находит факт, если он есть в контексте и не потерялся в середине длинного текста."""
    if FAKT not in kontekst:
        return "Не знаю."
    if tokeny(kontekst) > PORG_SEREDINY and 0.2 < polozhenie_fakta < 0.8:
        return "Не знаю."                                   # «потерянная середина»
    return "Ольга Петровна, кабинет 115."


def slova(tekst):
    return {s[:5] for s in re.findall(r"[а-яё]+", tekst.lower()) if len(s) > 3}


def rag(abzacy, vopros):
    """Поиск по словам (тема 2): KUSKOV_V_RAG абзацев с наибольшим совпадением слов."""
    ocenki = sorted(abzacy, key=lambda a: len(slova(a) & slova(vopros)), reverse=True)
    naydeno = [a for a in ocenki[:KUSKOV_V_RAG] if slova(a) & slova(vopros)]
    return "\n".join(naydeno)


print(f"{'документ':>18} {'где факт':>9} | {'всё в окно':^30} | {'RAG':^30}")
print(f"{'':>18} {'':>9} | {'токенов':>8} {'$ в день':>9} {'ответ':>11} | {'токенов':>8} {'$ в день':>9} {'ответ':>11}")
print("-" * 86)
for abzacev in (10, 300, 1000, 3000):
    for gde in ("начало", "середина", "конец"):
        abzacy, polozhenie = sdelat_dokument(abzacev, gde)
        ves = "\n".join(abzacy)

        t_okno = tokeny(ves)
        if t_okno > OKNO:
            okno = f"{t_okno:>8} {'—':>9} {'не влезает':>11}"
        else:
            otvet = zaglushka_modeli(ves, polozhenie)
            okno = f"{t_okno:>8} {t_okno * CENA_VHODA / 1e6 * VOPROSOV_V_DEN:>9.2f} {'✅' if 'Ольга' in otvet else '❌ не нашла':>11}"

        kuski = rag(abzacy, VOPROS)
        t_rag = tokeny(kuski)
        otvet = zaglushka_modeli(kuski, 0.0)
        rag_stroka = f"{t_rag:>8} {t_rag * CENA_VHODA / 1e6 * VOPROSOV_V_DEN:>9.4f} {'✅' if 'Ольга' in otvet else '❌ не нашла':>11}"
        print(f"{str(abzacev) + ' абзацев':>18} {gde:>9} | {okno} | {rag_stroka}")
    print()

print("Слабое место RAG — вопрос другими словами:")
abzacy, polozhenie = sdelat_dokument(300, "середина")
for vopros in (VOPROS, VOPROS_INACHE):
    kuski = rag(abzacy, vopros)
    print(f"  «{vopros}»")
    print(f"      RAG: найдено кусков {len(kuski.splitlines())}, ответ: {zaglushka_modeli(kuski, 0.0)}")
    # Модели всё равно, какими словами спросили: весь документ у неё перед глазами.
    print(f"      всё в окно: ответ: {zaglushka_modeli(chr(10).join(abzacy), polozhenie)}")
