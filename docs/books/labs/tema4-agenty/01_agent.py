# Агент с двумя инструментами и четырьмя границами:
# лимит шагов, ловля повторов, разрешение на опасное действие, набор инструментов.
# Вместо настоящей модели — функция model(), которая решает по простым правилам.

# --- НАСТРОЙКИ ---
MAX_SHAGOV = 6              # больше стольких шагов агент сделать не может
OPASNYE = {"udalit_fayl"}   # инструменты, требующие разрешения человека
RAZRESHAT_OPASNOE = False   # что "ответит человек", когда спросят разрешение

PRAVILA_SHKOLY = [
    "Кружок робототехники: вторник и четверг, 15:40, кабинет 204",
    "Библиотека открыта с 8:30 до 17:00",
    "Столовая работает с 9:00 до 15:00",
]


# --- ИНСТРУМЕНТЫ ---
def poisk(zapros):
    """Ищем строку правил, где встречается запрос (упрощённый поиск из темы 2)."""
    for stroka in PRAVILA_SHKOLY:
        if zapros.lower()[:7] in stroka.lower():
            return stroka
    return "ничего не найдено"


def raznica_minut(vyrazhenie):
    """Считает разницу двух времён вида '17:00-15:40' в минутах."""
    konec, nachalo = vyrazhenie.split("-")
    ch1, m1 = (int(x) for x in konec.split(":"))
    ch2, m2 = (int(x) for x in nachalo.split(":"))
    return str((ch1 * 60 + m1) - (ch2 * 60 + m2))


def udalit_fayl(imya):
    return f"файл {imya} удалён"


INSTRUMENTY = {"poisk": poisk, "raznica_minut": raznica_minut, "udalit_fayl": udalit_fayl}


def model(zadacha, istoriya):
    """Заглушка вместо модели: решает следующий шаг по тому, что уже известно.

    Настоящая модель делала бы то же самое, только сама, глядя на текст истории.
    """
    izvestno = " ".join(istoriya)

    if "удали" in zadacha.lower():
        return "ВЫЗОВ udalit_fayl | ocenki.txt"

    if "зациклись" in zadacha.lower():
        return "ВЫЗОВ poisk | столовая"        # намеренно один и тот же вызов

    if "робототехник" not in izvestno:
        return "ВЫЗОВ poisk | робототехника"
    if "Библиотека" not in izvestno:
        return "ВЫЗОВ poisk | библиотека"
    if "raznica_minut" not in izvestno:
        return "ВЫЗОВ raznica_minut | 17:00-15:40"
    return "ОТВЕТ: кружок в 15:40, до закрытия библиотеки остаётся "\
           + istoriya[-1].split(": ")[-1] + " минут"


def zapustit_agenta(zadacha):
    print("=" * 64)
    print(f"ЗАДАЧА: {zadacha}\n")

    istoriya = []
    byvshie_vyzovy = set()          # для ловли повторов

    # ГРАНИЦА 1: лимит шагов — цикл физически не может идти вечно.
    for nomer_shaga in range(1, MAX_SHAGOV + 1):
        reshenie = model(zadacha, istoriya)

        if reshenie.startswith("ОТВЕТ: "):
            print(f"  шаг {nomer_shaga}: модель готова ответить")
            print(f"  {reshenie}\n")
            return

        _, telo = reshenie.split("ВЫЗОВ ")
        imya, parametr = [chast.strip() for chast in telo.split("|")]
        print(f"  шаг {nomer_shaga}: модель просит {imya}({parametr})")

        # ГРАНИЦА 2: ловля повторов.
        if (imya, parametr) in byvshie_vyzovy:
            print("  СТОП: агент зациклился — этот вызов уже был\n")
            return
        byvshie_vyzovy.add((imya, parametr))

        # ГРАНИЦА 3: разрешение человека на опасное действие.
        if imya in OPASNYE:
            print(f"  ! опасное действие, спрашиваем человека: выполнить {imya}?")
            if not RAZRESHAT_OPASNOE:
                print("  СТОП: человек не разрешил\n")
                return
            print("  человек разрешил")

        # ГРАНИЦА 4: вызывать можно только известные инструменты.
        if imya not in INSTRUMENTY:
            print(f"  СТОП: инструмента {imya} не существует\n")
            return

        rezultat = INSTRUMENTY[imya](parametr)
        print(f"  шаг {nomer_shaga}: получен результат — {rezultat}")
        istoriya.append(f"{imya}: {rezultat}")

    print(f"  СТОП: закончился лимит в {MAX_SHAGOV} шагов\n")


zapustit_agenta("Во сколько робототехника и сколько минут до закрытия библиотеки?")
zapustit_agenta("Удали файл с оценками")
zapustit_agenta("Зациклись, пожалуйста")
