# Цикл "модель просит инструмент -> программа выполняет -> модель отвечает".
# Настоящую модель заменяет функция-заглушка, чтобы был виден сам механизм.

# --- НАСТРОЙКИ ---
VOPROSY = [
    "Какая погода в Москве?",
    "Сколько будет 17 умножить на 6?",
    "Привет!",
]
MAX_SHAGOV = 3        # ограничение: сколько раз модель может просить инструмент

# Игрушечная "база погоды" — чтобы не ходить в интернет.
POGODA = {"Москва": "+5, облачно", "Сочи": "+18, солнечно"}


# --- ИНСТРУМЕНТЫ: обычные функции ---
def uznat_pogodu(gorod):
    return POGODA.get(gorod, "нет данных по этому городу")


def poschitat(vyrazhenie):
    a, b = vyrazhenie.split("*")
    return str(int(a) * int(b))


INSTRUMENTY = {"uznat_pogodu": uznat_pogodu, "poschitat": poschitat}


def model(istoriya):
    """Заглушка вместо настоящей модели.

    Возвращает либо просьбу вызвать инструмент, либо готовый ответ.
    Настоящая модель делала бы то же самое, но решала бы сама.
    """
    vopros = istoriya[0]
    uzhe_vyzyvali = [shag for shag in istoriya if shag.startswith("результат")]

    if uzhe_vyzyvali:
        # Инструмент уже отработал — пишем финальный ответ человеку.
        return "ОТВЕТ: " + uzhe_vyzyvali[-1].replace("результат: ", "")

    if "погода" in vopros.lower():
        return "ВЫЗОВ: uznat_pogodu | Москва"
    if "умножить" in vopros.lower():
        return "ВЫЗОВ: poschitat | 17*6"
    return "ОТВЕТ: Привет! Чем помочь?"


def zapustit_agenta(vopros):
    istoriya = [vopros]
    print(f"Вопрос: {vopros}")

    for nomer_shaga in range(1, MAX_SHAGOV + 1):
        reshenie = model(istoriya)

        if reshenie.startswith("ОТВЕТ: "):
            print(f"  шаг {nomer_shaga}: модель отвечает человеку")
            print(f"  {reshenie}\n")
            return

        # Модель попросила инструмент — выполняем его обычным кодом.
        _, telo = reshenie.split("ВЫЗОВ: ")
        imya, parametr = [chast.strip() for chast in telo.split("|")]
        print(f"  шаг {nomer_shaga}: модель просит инструмент {imya}({parametr})")

        rezultat = INSTRUMENTY[imya](parametr)
        print(f"  шаг {nomer_shaga}: программа вернула {rezultat!r}")
        istoriya.append(f"результат: {rezultat}")

    print("  остановились: закончился лимит шагов\n")


for vopros in VOPROSY:
    zapustit_agenta(vopros)
