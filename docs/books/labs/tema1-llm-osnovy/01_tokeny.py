# Учебная модель токенизатора: режем текст по списку частых кусочков.
# Настоящий токенизатор устроен сложнее, но идея ровно такая же.

# --- НАСТРОЙКИ ---
# Список частых кусочков. Важно: сначала длинные, потом короткие,
# чтобы "программ" отрезалось раньше, чем "про".
CHASTYE_KUSOCHKI = [
    "программ", "компьютер", "привет", "мир", "hello", "world",
    "program", "ming", "comput", "иров", "ание", "ер", "ик",
]

TEKSTY = [
    "привет мир",
    "hello world",
    "программирование",
    "programming",
]


def razrezat(text):
    """Возвращает список токенов для строки text."""
    tokeny = []
    ostatok = text
    while ostatok:
        # Пробел — это тоже токен, не забываем про него.
        if ostatok[0] == " ":
            tokeny.append(" ")
            ostatok = ostatok[1:]
            continue

        # Ищем самый длинный кусочек из списка, с которого начинается остаток.
        naydeno = None
        for kusochek in CHASTYE_KUSOCHKI:
            if ostatok.startswith(kusochek):
                if naydeno is None or len(kusochek) > len(naydeno):
                    naydeno = kusochek

        if naydeno:
            tokeny.append(naydeno)
            ostatok = ostatok[len(naydeno):]
        else:
            # Ничего не подошло — отрезаем одну букву.
            tokeny.append(ostatok[0])
            ostatok = ostatok[1:]

    return tokeny


for text in TEKSTY:
    tokeny = razrezat(text)
    print(f"{text!r}")
    print(f"  токены: {tokeny}")
    print(f"  букв: {len(text)}, токенов: {len(tokeny)}")
    print()
