# Один и тот же диалог из 30 ходов — пять способов отправлять историю модели.
# Считаем, сколько токенов уходит за весь разговор, и проверяем главное:
# помнит ли бот в конце, как зовут собеседника.
# Настоящую модель заменяет заглушка: она «видит» только то, что есть в запросе.

# --- НАСТРОЙКИ ---
HODOV = 30                 # сколько вопросов задаёт ученик
OKNO = 6                   # сколько последних сообщений оставляет окно
OBREZAT_INSTRUMENT = 120   # до скольких символов режем результат инструмента
PORG_PERESKAZA = 900       # пересказываем, когда история длиннее стольких токенов
CENA_VHODA = 0.10          # долларов за 1 млн входных токенов
SKIDKA_KESHA = 0.20        # повторённое начало запроса стоит 20% цены (как у qwen3.7-flash)

PRAVILA = "Ты помощник школы №7. Отвечай кратко и вежливо. " * 20   # длинное неизменное начало


def tokeny(tekst):
    """Грубая оценка: русский текст — примерно токен на 2 символа (тема 1)."""
    return len(tekst) // 2


def razgovor():
    """Ход 1 — знакомство, каждый 5-й ход вызывает инструмент с длинным ответом."""
    hody = [("user", "Привет! Меня зовут Аня, я учусь в 9Б.")]
    for n in range(2, HODOV):
        if n % 5 == 0:
            hody.append(("user", f"Покажи расписание на день {n}."))
            hody.append(("tool", f"Расписание дня {n}: " + "урок, кабинет, учитель, перемена; " * 30))
        else:
            hody.append(("user", f"Вопрос номер {n} про домашнее задание."))
    hody.append(("user", "Кстати, как меня зовут?"))
    return hody


def zaglushka_modeli(soobshcheniya):
    """Отвечает на последний вопрос. Имя знает, только если оно есть в запросе."""
    vopros = soobshcheniya[-1][1]
    if "как меня зовут" in vopros:
        vidit = " ".join(tekst for _, tekst in soobshcheniya)
        return "Тебя зовут Аня." if "Аня" in vidit else "Не знаю, ты не говорила."
    return "Хорошо, вот короткий ответ на твой вопрос."


# ---------- Пять стратегий: что именно уходит модели на очередном ходе ----------

def vsya_istoriya(istoriya, pamyat):
    return istoriya


def okno(istoriya, pamyat):
    return istoriya[-OKNO:]


def okno_i_obrezka(istoriya, pamyat):
    return [(rol, tekst[:OBREZAT_INSTRUMENT] + "…" if rol == "tool" else tekst)
            for rol, tekst in istoriya[-OKNO:]]


def pereskaz(istoriya, pamyat):
    """Когда история разрослась — старое заменяем пересказом, последние сообщения оставляем."""
    if sum(tokeny(t) for _, t in istoriya) <= PORG_PERESKAZA:
        return istoriya
    staroe, novoe = istoriya[:-OKNO], istoriya[-OKNO:]
    # В жизни пересказ пишет сама модель. Заглушка оставляет фразы, похожие на факты.
    fakty = [t for rol, t in staroe if rol == "user" and ("зовут" in t or "учусь" in t)]
    return [("system", "Кратко о начале разговора: " + " ".join(fakty))] + novoe


def dolgaya_pamyat(istoriya, pamyat):
    """Факты выписаны отдельно (тема 4) и подставляются в каждый запрос; история — окном."""
    return [("system", "Известно о собеседнике: " + "; ".join(pamyat))] + istoriya[-OKNO:]


def zapomnit_fakty(soobshchenie, pamyat):
    rol, tekst = soobshchenie
    if rol == "user" and "зовут" in tekst and "как меня" not in tekst:
        pamyat.append(tekst)


STRATEGII = [
    ("вся история", vsya_istoriya),
    ("окно", okno),
    ("окно + обрезка", okno_i_obrezka),
    ("пересказ", pereskaz),
    ("долгая память", dolgaya_pamyat),
]

print(f"{'Стратегия':<16} {'токенов за диалог':>18} {'последний запрос':>17} {'1000 диалогов, $':>17}  ответ на «как меня зовут?»")
print("-" * 100)
rost = []
for nazvanie, strategiya in STRATEGII:
    istoriya, pamyat, vsego, posledniy = [], [], 0, 0
    for soobshchenie in razgovor():
        istoriya.append(soobshchenie)
        zapomnit_fakty(soobshchenie, pamyat)
        if soobshchenie[0] == "tool":
            continue                       # результат инструмента не новый вопрос
        zapros = [("system", PRAVILA)] + strategiya(istoriya, pamyat)
        posledniy = sum(tokeny(t) for _, t in zapros)
        vsego += posledniy
        if nazvanie == "вся история":
            rost.append(posledniy)
        otvet = zaglushka_modeli(zapros)
        istoriya.append(("assistant", otvet))
    print(f"{nazvanie:<16} {vsego:>18} {posledniy:>17} {vsego * 1000 * CENA_VHODA / 1e6:>17.2f}  {otvet}")

print("\nКак растёт запрос, если отправлять всю историю (токенов на ходе):")
print("  " + "  ".join(f"ход {i + 1}: {t}" for i, t in enumerate(rost) if i % 5 == 0 or i == len(rost) - 1))

pravila = tokeny(PRAVILA)
bez_kesha = pravila * HODOV * 1000 * CENA_VHODA / 1e6
s_keshem = (pravila + pravila * (HODOV - 1) * SKIDKA_KESHA) * 1000 * CENA_VHODA / 1e6
print(f"\nНеизменные правила в начале — {pravila} токенов на каждом из {HODOV} ходов, 1000 диалогов:")
print(f"  без кэша: ${bez_kesha:.2f}   с кэшем начала: ${s_keshem:.2f}   (в {bez_kesha / s_keshem:.1f} раза дешевле)")
