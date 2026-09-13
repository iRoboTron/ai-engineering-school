# Ненадёжный сервис модели и четыре способа с ним работать.
# Заглушка иногда отвечает ошибкой, иногда думает слишком долго, иногда присылает
# испорченный JSON. Считаем, сколько запросов ученика в итоге получили нормальный ответ
# и сколько времени это заняло. Паузы не настоящие — время только считается.

import json
import random

# --- НАСТРОЙКИ ---
ZAPROSOV = 200           # сколько вопросов задают ученики
SEED = 7                 # поменяй — получишь другую «неудачную неделю»
TAYMAUT = 10.0           # секунд ждём ответа, дальше считаем, что не дождались
POPYTOK = 4              # сколько раз всего пробуем одну модель
PERVAYA_PAUZA = 1.0      # пауза перед первым повтором, дальше растёт вдвое

# Поведение моделей: вероятности разных бед на один запрос.
OSNOVNAYA = {"imya": "основная", "429": 0.15, "500": 0.05, "dolgo": 0.05, "bityy_json": 0.05, "vremya": 1.5}
REZERVNAYA = {"imya": "резервная", "429": 0.02, "500": 0.02, "dolgo": 0.01, "bityy_json": 0.10, "vremya": 2.5}
DOLYA_PLOHIH_VOPROSOV = 0.03     # вопрос сломан сам (400): повторять бесполезно
LEZHIT_S = 0.8                   # с этой доли потока основная модель «ложится» совсем (503)

VREMENNYE = {429, 500, 502, 503, 504}     # подождать и повторить — может помочь
POSTOYANNYE = {400, 401, 413}             # повтор ничего не изменит


class Oshibka(Exception):
    def __init__(self, kod, potracheno):
        super().__init__(kod)
        self.kod, self.potracheno = kod, potracheno


def zaglushka_api(model, vopros_plohoy, sluchay):
    """Один запрос. Возвращает (текст, секунд) или бросает Oshibka."""
    if vopros_plohoy:
        raise Oshibka(400, 0.2)
    if model.get("lezhit"):
        raise Oshibka(503, 0.3)
    r = sluchay.random()
    porog = 0.0
    for kod, klyuch in ((429, "429"), (500, "500")):
        porog += model[klyuch]
        if r < porog:
            raise Oshibka(kod, 0.3)
    porog += model["dolgo"]
    if r < porog:
        return '{"otvet": "..."}', 60.0                    # модель «зависла» на минуту
    porog += model["bityy_json"]
    if r < porog:
        return '{"otvet": "Каникулы с 28 окт', model["vremya"]  # оборван на полуслове
    return '{"otvet": "Каникулы с 28 октября"}', model["vremya"]


def proverit_json(tekst):
    try:
        return "otvet" in json.loads(tekst)
    except json.JSONDecodeError:
        return False


# ---------- Способы ----------

def bez_zashchity(vopros_plohoy, sluchay, zhurnal):
    tekst, sekund = zaglushka_api(OSNOVNAYA, vopros_plohoy, sluchay)   # ошибка — упадёт
    return tekst, sekund


def odna_model(model, vopros_plohoy, sluchay, zhurnal, proveryat_json):
    """Тайм-аут + повторы с растущей паузой, только для временных ошибок."""
    vremya, pauza = 0.0, PERVAYA_PAUZA
    for popytka in range(1, POPYTOK + 1):
        try:
            tekst, sekund = zaglushka_api(model, vopros_plohoy, sluchay)
            if sekund > TAYMAUT:
                vremya += TAYMAUT
                raise Oshibka("тайм-аут", 0)
            vremya += sekund
            if proveryat_json and not proverit_json(tekst):
                raise Oshibka("битый JSON", 0)
            return tekst, vremya
        except Oshibka as e:
            vremya += e.potracheno
            zhurnal[e.kod] = zhurnal.get(e.kod, 0) + 1
            if e.kod in POSTOYANNYE:
                raise Oshibka(e.kod, vremya)                  # не повторяем: бесполезно
            if popytka < POPYTOK:
                vremya += pauza * (0.5 + sluchay.random())     # пауза с разбросом
                pauza *= 2
    raise Oshibka("попытки кончились", vremya)


def povtory(vopros_plohoy, sluchay, zhurnal):
    return odna_model(OSNOVNAYA, vopros_plohoy, sluchay, zhurnal, proveryat_json=False)


def povtory_i_rezerv(vopros_plohoy, sluchay, zhurnal):
    try:
        return odna_model(OSNOVNAYA, vopros_plohoy, sluchay, zhurnal, proveryat_json=False)
    except Oshibka as e:
        if e.kod in POSTOYANNYE:
            raise
        tekst, vremya = odna_model(REZERVNAYA, vopros_plohoy, sluchay, zhurnal, proveryat_json=False)
        return tekst, vremya + e.potracheno


def vse_zashchity(vopros_plohoy, sluchay, zhurnal):
    try:
        return odna_model(OSNOVNAYA, vopros_plohoy, sluchay, zhurnal, proveryat_json=True)
    except Oshibka as e:
        if e.kod in POSTOYANNYE:
            raise
        tekst, vremya = odna_model(REZERVNAYA, vopros_plohoy, sluchay, zhurnal, proveryat_json=True)
        return tekst, vremya + e.potracheno


SPOSOBY = [
    ("без защиты", bez_zashchity),
    ("тайм-аут + повторы", povtory),
    ("+ резервная модель", povtory_i_rezerv),
    ("+ проверка JSON", vse_zashchity),
]

print(f"{ZAPROSOV} вопросов; примерно {DOLYA_PLOHIH_VOPROSOV:.0%} сломаны сами; "
      f"последние {1 - LEZHIT_S:.0%} основная модель не отвечает совсем\n")
print(f"{'Способ':<22} {'годных':>7} {'упало':>6} {'битых':>6} {'ср. время':>10} {'макс':>7}")
print("-" * 64)
for nazvanie, sposob in SPOSOBY:
    godnyh = upalo = bityh = 0
    vremena, zhurnal = [], {}
    for nomer in range(ZAPROSOV):
        # У каждого вопроса своя «судьба», одинаковая для всех способов — сравнение честное.
        sluchay = random.Random(SEED * 100_000 + nomer)
        plohoy = sluchay.random() < DOLYA_PLOHIH_VOPROSOV
        OSNOVNAYA["lezhit"] = nomer >= ZAPROSOV * LEZHIT_S
        try:
            tekst, vremya = sposob(plohoy, sluchay, zhurnal)
            if proverit_json(tekst):
                godnyh += 1
            else:
                bityh += 1                             # «ответил», но показать нельзя
            vremena.append(vremya)
        except Oshibka as e:
            upalo += 1
            vremena.append(e.potracheno)
    print(f"{nazvanie:<22} {godnyh:>7} {upalo:>6} {bityh:>6} {sum(vremena) / len(vremena):>8.1f} с {max(vremena):>5.1f} с")
    if zhurnal:
        print(f"{'':<22} неудачные попытки: " + ", ".join(f"{k}: {v}" for k, v in zhurnal.items()))
