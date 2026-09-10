# Мини-RAG целиком: режем документ на чанки, ищем подходящие по словам,
# собираем запрос к модели. Саму модель не зовём — печатаем то, что ей ушло бы.

# --- НАСТРОЙКИ ---
SKOLKO_CHANKOV_BRAT = 2      # сколько лучших кусков класть в запрос

DOKUMENT = """
Кружок робототехники: вторник и четверг, 15:40, кабинет 204. Руководитель Иванов П. С.
Кружок рисования: среда, 16:00, кабинет 112. Приносить свои краски.
Столовая работает с 9:00 до 15:00. Завтрак с 9:00 до 9:30.
Библиотека открыта с 8:30 до 17:00, кроме пятницы.
"""

VOPROSY = [
    "во сколько кружок робототехники",
    "когда работает библиотека",
    "сколько стоит проезд на автобусе",   # ответа в документе нет
]

# Слова, которые встречаются почти везде и мешают искать.
STOP_SLOVA = {"во", "и", "с", "до", "на", "в", "у", "не", "сколько", "когда"}


def narezat_na_chanki(text):
    """Режем документ по строкам: здесь каждая строка — отдельная тема."""
    return [stroka.strip() for stroka in text.strip().split("\n") if stroka.strip()]


def slova(text):
    """Разбиваем текст на слова, убираем знаки и стоп-слова."""
    ochishchennyy = "".join(bukva.lower() if bukva.isalnum() else " " for bukva in text)
    return {s for s in ochishchennyy.split() if s not in STOP_SLOVA}


def obrezat(slovo):
    """Грубое приведение к общей форме: оставляем первые 6 букв.

    Так 'робототехники' и 'робототехников' станут одинаковыми.
    """
    return slovo[:6]


def naiti_chanki(vopros, chanki):
    """Считаем совпадения слов и возвращаем список (очки, чанк), лучшие сверху."""
    slova_voprosa = {obrezat(s) for s in slova(vopros)}
    ocenennye = []
    for chank in chanki:
        slova_chanka = {obrezat(s) for s in slova(chank)}
        ochki = len(slova_voprosa & slova_chanka)
        ocenennye.append((ochki, chank))
    ocenennye.sort(key=lambda para: para[0], reverse=True)
    return ocenennye


def sobrat_zapros(vopros, naydennye_chanki):
    """Собираем текст запроса к модели — с правилом отвечать только по тексту."""
    tekst = "\n".join(f"- {chank}" for chank in naydennye_chanki)
    return (
        "Ответь на вопрос, пользуясь ТОЛЬКО текстом ниже.\n"
        "Если ответа в тексте нет — напиши «в документах этого нет».\n\n"
        f"ТЕКСТ:\n{tekst}\n\n"
        f"ВОПРОС: {vopros}"
    )


chanki = narezat_na_chanki(DOKUMENT)
print(f"Документ разрезан на {len(chanki)} чанков.\n")

for vopros in VOPROSY:
    print("=" * 60)
    print(f"ВОПРОС: {vopros}\n")

    ocenennye = naiti_chanki(vopros, chanki)
    print("Что нашёл поиск (очки — число совпавших слов):")
    for ochki, chank in ocenennye:
        print(f"  {ochki} | {chank[:55]}...")

    luchshie = [chank for ochki, chank in ocenennye[:SKOLKO_CHANKOV_BRAT] if ochki > 0]

    if not luchshie:
        print("\nНичего не нашлось — модель звать незачем, отвечаем «в документах этого нет».\n")
        continue

    print("\nЗапрос, который ушёл бы модели:")
    print("-" * 60)
    print(sobrat_zapros(vopros, luchshie))
    print("-" * 60 + "\n")
