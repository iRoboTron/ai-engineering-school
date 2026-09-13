# Школьный бот за месяц: 40 вопросов, две модели, шесть способов их использовать.
# Считаем деньги, долю хороших ответов и время. Модели — заглушки с ценой и скоростью,
# похожими на настоящие: дешёвая быстрая и дорогая сильная.

import re

# --- НАСТРОЙКИ ---
DESHEVAYA = {"imya": "дешёвая", "vhod": 0.03, "vyhod": 0.13, "tokenov_v_sekundu": 150, "do_pervogo": 0.3}
SILNAYA = {"imya": "сильная", "vhod": 3.00, "vyhod": 15.00, "tokenov_v_sekundu": 50, "do_pervogo": 1.2}
PRAVILA_TOKENOV = 300            # правила бота в каждом запросе
KOROTKO_TOKENOV = 60             # длина ответа, если попросить коротко и поставить max_tokens
PARALLELNO = 5                   # сколько запросов отправлять одновременно
POVTOROV_MESYATSEV = 1000        # во сколько раз умножить, чтобы получить «месяц работы школы»

SLOZHNYE_PRIZNAKI = ["почему", "объясни", "сравни", "докажи", "реши"]

VOPROSY = [
    "Во сколько начало уроков?", "Где кабинет 204?", "Почему небо голубое?",
    "Во сколько начало уроков?", "Когда каникулы?", "Объясни теорему Пифагора",
    "Где столовая?", "Во сколько начало уроков?", "Сравни Пушкина и Лермонтова",
    "Когда каникулы?", "Где кабинет 204?", "Реши уравнение 2x + 3 = 11",
    "Нужна ли сменная обувь?", "Во сколько начало уроков?", "Почему идёт дождь?",
    "Где столовая?", "Когда каникулы?", "Докажи, что корень из двух иррационален",
    "Нужна ли сменная обувь?", "Во сколько начало уроков?",
] * 2


def slozhnyy(vopros):
    return any(p in vopros.lower() for p in SLOZHNYE_PRIZNAKI)


def zaglushka(model, vopros, korotko):
    """Возвращает (токенов на выходе, хороший ли ответ). Дешёвая модель не справляется со сложным."""
    if slozhnyy(vopros):
        tokenov = 300
        horosho = model is SILNAYA
    else:
        tokenov = KOROTKO_TOKENOV if korotko else 250     # без ограничения модель «болтает»
        horosho = True
    return tokenov, horosho


def tokeny(tekst):
    return len(tekst) // 2 + PRAVILA_TOKENOV


def normalizovat(vopros):
    """Ключ кэша: регистр и знаки препинания не должны мешать узнать тот же вопрос."""
    return re.sub(r"[^\w\s]", "", vopros.lower()).strip()


def progon(nazvanie, vybrat_model, kesh=False, korotko=False):
    dengi, horoshih, kesh_popadaniy, vremena = 0.0, 0, 0, []
    zapomneno = {}
    for vopros in VOPROSY:
        klyuch = normalizovat(vopros)
        if kesh and klyuch in zapomneno:
            kesh_popadaniy += 1
            horoshih += zapomneno[klyuch]
            vremena.append(0.01)                          # ответ из словаря — мгновенно
            continue
        model = vybrat_model(vopros)
        vyhod, horosho = zaglushka(model, vopros, korotko)
        dengi += (tokeny(vopros) * model["vhod"] + vyhod * model["vyhod"]) / 1e6
        horoshih += horosho
        vremena.append(model["do_pervogo"] + vyhod / model["tokenov_v_sekundu"])
        if kesh:
            zapomneno[klyuch] = horosho
    podryad = sum(vremena)
    # Параллельно: запросы идут пачками, пачка ждёт самый долгий из своих.
    parallelno = sum(max(vremena[i:i + PARALLELNO]) for i in range(0, len(vremena), PARALLELNO))
    print(f"{nazvanie:<32} ${dengi * POVTOROV_MESYATSEV:>8.2f}  {horoshih / len(VOPROSY):>5.0%}"
          f"  {kesh_popadaniy:>4}  {podryad:>7.1f} с  {parallelno:>6.1f} с")
    return dengi


print(f"{len(VOPROSY)} вопросов × {POVTOROV_MESYATSEV} (месяц работы школы)\n")
print(f"{'Способ':<32} {'деньги':>9}  {'хорошо':>6}  {'кэш':>4}  {'подряд':>9}  {'пачками':>8}")
print("-" * 80)
vse_silnaya = progon("всё на сильной", lambda v: SILNAYA)
progon("всё на сильной + коротко", lambda v: SILNAYA, korotko=True)
progon("всё на дешёвой", lambda v: DESHEVAYA)
progon("маршрутизатор", lambda v: SILNAYA if slozhnyy(v) else DESHEVAYA)
progon("маршрутизатор + кэш", lambda v: SILNAYA if slozhnyy(v) else DESHEVAYA, kesh=True)
luchshiy = progon("маршрутизатор + кэш + коротко", lambda v: SILNAYA if slozhnyy(v) else DESHEVAYA, kesh=True, korotko=True)

print(f"\nПоследний способ дешевле «всё на сильной» в {vse_silnaya / luchshiy:.0f} раз.")

print("\nИз чего складывается цена одного сложного вопроса на сильной модели:")
vhod = tokeny("Объясни теорему Пифагора") * SILNAYA["vhod"] / 1e6
vyhod = 300 * SILNAYA["vyhod"] / 1e6
print(f"  вход  {tokeny('Объясни теорему Пифагора'):>4} токенов × ${SILNAYA['vhod']}/1М = ${vhod:.5f}")
print(f"  выход  300 токенов × ${SILNAYA['vyhod']}/1М = ${vyhod:.5f}  ← выход дороже, хотя токенов меньше")
