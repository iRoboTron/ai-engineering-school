# Измеряем качество поиска на эталонном наборе — и сравниваем два варианта поиска.

# --- НАСТРОЙКИ ---
SKOLKO_BRAT = 2       # сколько лучших чанков считаем "найденными"

CHANKI = [
    "Кружок робототехники: вторник и четверг, 15:40, кабинет 204",
    "Кружок рисования: среда, 16:00, кабинет 112",
    "Столовая работает с 9:00 до 15:00",
    "Библиотека открыта с 8:30 до 17:00",
]

# Эталонный набор: вопрос -> какой чанк ДОЛЖЕН найтись (None = ответа нет вовсе).
ETALONNYY_NABOR = {
    "во сколько кружок робототехники": 0,
    "когда занятия у робототехников": 0,      # те же слова другими словами
    "где кабинет рисования": 1,
    "когда работает библиотека": 3,
    "до скольки открыта читальня": 3,          # "читальня" вместо "библиотеки"
    "сколько стоит проезд на автобусе": None,  # ответа в документах нет
    "во сколько работает бассейн": None,       # бассейна в правилах тоже нет
}

STOP_SLOVA = {"во", "и", "с", "до", "на", "в", "у", "не", "сколько", "когда", "где", "скольки"}


def slova(text):
    ochishchennyy = "".join(b.lower() if b.isalnum() else " " for b in text)
    return {s for s in ochishchennyy.split() if s not in STOP_SLOVA}


def poisk_prostoy(vopros):
    """Вариант 1: считаем совпадения слов как есть."""
    slova_voprosa = slova(vopros)
    ocenki = [(len(slova_voprosa & slova(chank)), nomer) for nomer, chank in enumerate(CHANKI)]
    ocenki.sort(reverse=True)
    return [nomer for ochki, nomer in ocenki[:SKOLKO_BRAT] if ochki > 0]


def poisk_uluchshennyy(vopros):
    """Вариант 2: то же самое, но слова обрезаем до 6 букв.

    Тогда 'робототехников' и 'робототехники' совпадут.
    """
    slova_voprosa = {s[:6] for s in slova(vopros)}
    ocenki = []
    for nomer, chank in enumerate(CHANKI):
        slova_chanka = {s[:6] for s in slova(chank)}
        ocenki.append((len(slova_voprosa & slova_chanka), nomer))
    ocenki.sort(reverse=True)
    return [nomer for ochki, nomer in ocenki[:SKOLKO_BRAT] if ochki > 0]


def izmerit(poisk, nazvanie):
    """Прогоняем весь эталонный набор и считаем, в скольких случаях всё верно."""
    print(f"--- {nazvanie} ---")
    verno = 0
    provaly = []

    for vopros, nuzhnyy_chank in ETALONNYY_NABOR.items():
        naydeno = poisk(vopros)

        if nuzhnyy_chank is None:
            # Правильное поведение: не найти ничего.
            uspekh = len(naydeno) == 0
        else:
            uspekh = nuzhnyy_chank in naydeno

        if uspekh:
            verno += 1
        else:
            provaly.append((vopros, nuzhnyy_chank, naydeno))

    vsego = len(ETALONNYY_NABOR)
    print(f"верно: {verno} из {vsego} = {round(100 * verno / vsego)}%")

    if provaly:
        print("провалы:")
        for vopros, nuzhnyy, naydeno in provaly:
            print(f"  {vopros!r}: нужен чанк {nuzhnyy}, найдено {naydeno}")
    print()
    return verno


bylo = izmerit(poisk_prostoy, "Вариант 1: поиск по словам как есть")
stalo = izmerit(poisk_uluchshennyy, "Вариант 2: слова обрезаны до 6 букв")

print("=" * 60)
if stalo > bylo:
    print(f"Улучшение помогло: было {bylo}, стало {stalo}. Оставляем.")
elif stalo == bylo:
    print(f"Ничего не изменилось ({bylo}). Смысла в усложнении нет.")
else:
    print(f"Стало хуже: было {bylo}, стало {stalo}. Откатываем.")
