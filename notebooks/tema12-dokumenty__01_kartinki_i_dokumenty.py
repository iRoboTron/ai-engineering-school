# %% [markdown]
# # Лаборатория 12. Картинки и длинные документы
#
# **Что мы сделаем:** нарисуем картинки прямо в Python — поэтому правильные ответы будут
# известны заранее, и код сможет честно проверить модель. Потом спрячем факт в длинный
# документ и сравним «всё в окно» с RAG по точности и цене.
#
# | Шаг | Что узнаем |
# |---|---|
# | 1 | Рисуем расписание и превращаем картинку в запрос |
# | 2 | Модель читает расписание — код проверяет каждую клетку |
# | 3 | Сколько стоит картинка: три размера, три цены, три точности |
# | 4 | Модель считает фигуры — и ошибается |
# | 5 | Длинный документ целиком: факт в начале, середине и конце |
# | 6 | Тот же вопрос через RAG: цена и точность |
# | 7 | Вопрос другими словами: слабое место RAG |
#
# **Что понадобится:** код класса от учителя. **Запросов:** около 25.

# %%
!pip -q install openai pillow

# %%
import base64
import getpass
import io
import json
import os
import random
import re
import urllib.request

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

ADRES = "https://ai9.adelfos.ru/api/v1"
MODEL = "qwen/qwen3.7-flash"          # понимает картинки

try:
    from google.colab import userdata
    KOD_KLASSA = userdata.get("AI9_KOD")
except Exception:
    KOD_KLASSA = os.environ.get("AI9_KOD") or getpass.getpass("Код класса: ")

client = OpenAI(base_url=ADRES, api_key=KOD_KLASSA, timeout=60)

# Цена входа нашей модели — из открытого каталога школьного сервера (тема 10).
with urllib.request.urlopen("https://ai9.adelfos.ru/api/catalog", timeout=60) as r:
    CENA_VHODA = next(float(m["prompt"]) * 1e6 for m in json.load(r)["models"] if m["id"] == MODEL)
print(f"Подключились. Цена входа {MODEL}: ${CENA_VHODA} за 1 млн токенов")

# %% [markdown]
# ## Шаг 1. Рисуем расписание
#
# Возьмём таблицу, про которую **мы точно знаем правду**, и нарисуем её картинкой.
# Так мы потом сможем проверить ответ модели кодом, клетка за клеткой.
#
# Для русских букв нужен шрифт с кириллицей. В Colab он обычно есть; если не нашёлся —
# картинка будет на английском, всё остальное работает так же.

# %%
PRAVDA = [
    {"predmet": "Алгебра", "vremya": "08:30", "kabinet": "204"},
    {"predmet": "Физика", "vremya": "09:25", "kabinet": "311"},
    {"predmet": "История", "vremya": "10:30", "kabinet": "115"},
    {"predmet": "Химия", "vremya": "11:35", "kabinet": "318"},
    {"predmet": "Литература", "vremya": "12:40", "kabinet": "207"},
    {"predmet": "Физкультура", "vremya": "13:35", "kabinet": "спортзал"},
]

SHRIFTY = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def nayti_shrift(razmer):
    for put in SHRIFTY:
        if os.path.exists(put):
            return ImageFont.truetype(put, razmer), True
    return ImageFont.load_default(), False


def narisovat_raspisanie(stroki):
    shrift, kirillica = nayti_shrift(34)
    img = Image.new("RGB", (1000, 120 + 80 * len(stroki)), "white")
    d = ImageDraw.Draw(img)
    zagolovki = ("Предмет", "Время", "Кабинет") if kirillica else ("Subject", "Time", "Room")
    kolonki = (40, 480, 700)
    for x, z in zip(kolonki, zagolovki):
        d.text((x, 40), z, fill="black", font=shrift)
    d.line((30, 100, 970, 100), fill="black", width=3)
    for i, s in enumerate(stroki):
        y = 130 + 80 * i
        for x, znachenie in zip(kolonki, (s["predmet"], s["vremya"], s["kabinet"])):
            d.text((x, y), znachenie, fill="black", font=shrift)
        d.line((30, y + 60, 970, y + 60), fill="#cccccc", width=1)
    return img, kirillica


def v_url(img, dlinnaya_storona):
    """Уменьшает картинку и превращает её в строку data:image/png;base64,... для запроса."""
    kopiya = img.copy()
    kopiya.thumbnail((dlinnaya_storona, dlinnaya_storona))
    bufer = io.BytesIO()
    kopiya.save(bufer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(bufer.getvalue()).decode(), kopiya.size


raspisanie, kirillica = narisovat_raspisanie(PRAVDA)
print("Кириллица в шрифте:", "есть" if kirillica else "нет — картинка будет на английском")
url, razmer = v_url(raspisanie, 1000)
print(f"Размер картинки: {razmer[0]}×{razmer[1]} точек, в запросе это {len(url):,} символов base64")
display(raspisanie)

# %% [markdown]
# Посмотри на последнюю строку перед картинкой: небольшая картинка — это десятки тысяч
# символов. Если бы школьный сервер считал её обычным текстом, запрос не прошёл бы
# лимит длины. Поэтому картинки он ограничивает отдельно: по числу и размеру.

# %% [markdown]
# ## Шаг 2. Модель читает расписание
#
# Отправляем картинку и просим JSON — список строк с тремя полями. Потом код сравнивает
# ответ с `PRAVDA`.

# %%
def sprosit_pro_kartinku(vopros, url, max_tokens=500, **dop):
    otvet = client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=max_tokens, **dop,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": vopros},
            {"type": "image_url", "image_url": {"url": url}},
        ]}],
    )
    return (otvet.choices[0].message.content or "").strip(), otvet.usage, otvet.model


def vytashchit_json(tekst):
    """Разбирает JSON из ответа. Возвращает (данные, что пришлось починить).

    Модели иногда оборачивают JSON в ```json ... ``` или теряют квадратные скобки списка.
    Такие мелочи чиним кодом, но честно запоминаем, что чинили.
    """
    chistyy = re.sub(r"^```(?:json)?|```$", "", tekst.strip(), flags=re.M).strip()
    for variant, pochinka in ((chistyy, "—"), ("[" + chistyy + "]", "дописаны [ ]")):
        try:
            return json.loads(variant), pochinka
        except json.JSONDecodeError:
            pass
    return None, "не JSON"


VOPROS_RASPISANIE = (
    "Перепиши расписание с картинки в JSON: список объектов с полями "
    '"predmet", "vremya", "kabinet". Только JSON, без пояснений.'
)


def proverit_raspisanie(dannye, pravda, pechatat=True):
    if not isinstance(dannye, list):
        if pechatat:
            print("❌ ответ не разобрался как список JSON")
        return 0, len(pravda) * 3
    verno = 0
    for i, pravilnaya in enumerate(pravda):
        stroka = dannye[i] if i < len(dannye) and isinstance(dannye[i], dict) else {}
        otmetki = []
        for pole in ("predmet", "vremya", "kabinet"):
            ok = str(stroka.get(pole, "")).strip().lower() == pravilnaya[pole].lower()
            verno += ok
            otmetki.append(f"{'✅' if ok else '❌'} {str(stroka.get(pole, '—')):<12}")
        if pechatat:
            print(f"   {pravilnaya['predmet']:<12} | " + " ".join(otmetki))
    return verno, len(pravda) * 3


tekst, usage, kto = sprosit_pro_kartinku(VOPROS_RASPISANIE, url)
print(f"Ответила {kto}, prompt_tokens = {usage.prompt_tokens}\n")
print("Начало сырого ответа:", tekst[:150].replace("\n", " "), "…\n")
dannye, pochinka = vytashchit_json(tekst)
print(f"Формат: {'годный' if pochinka == '—' else pochinka}\n")
verno, vsego = proverit_raspisanie(dannye, PRAVDA)
print(f"\nВерно клеток: {verno} из {vsego}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. **prompt_tokens** — около 640, и почти всё это картинка: текста в вопросе
#    на два десятка токенов.
# 2. Таблица проверки: крупный чёткий текст модель читает без ошибок. При подготовке
#    лаборатории вышло 18 из 18. Если у тебя где-то ❌ — посмотри, что именно: цифра
#    не та? Лишний пробел?
# 3. Проверка сделана **кодом**, а не глазами: ровно так проверяют ответы по картинкам
#    в настоящем проекте, когда правильный ответ можно знать или проверить.
#
# Если картинка на английском (не нашёлся шрифт), колонка «predmet» не совпадёт —
# смотри на время и кабинеты.

# %% [markdown]
# ## Шаг 3. Сколько стоит картинка
#
# Та же картинка в трёх размерах. Для каждого — сколько токенов и сколько клеток модель
# прочитала верно. Ищем разумный размер: дешевле, но без потери точности.

# %%
print(f"{'размер':>12} {'prompt_tokens':>14} {'$ за 1000 таких':>16} {'верно клеток':>13}  формат")
for storona in (300, 600, 1000):
    url_n, razmer_n = v_url(raspisanie, storona)
    tekst, usage, _ = sprosit_pro_kartinku(VOPROS_RASPISANIE, url_n)
    dannye, pochinka = vytashchit_json(tekst)
    verno, vsego = proverit_raspisanie(dannye, PRAVDA, pechatat=False)
    print(f"{razmer_n[0]:>5}×{razmer_n[1]:<6} {usage.prompt_tokens:>14} "
          f"{usage.prompt_tokens * CENA_VHODA / 1e6 * 1000:>16.4f} {verno:>7} из {vsego}  {pochinka}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. **prompt_tokens растёт с размером.** При подготовке лаборатории вышло 127, 259 и 639
#    токенов: картинка вдвое шире — токенов примерно вдвое-втрое больше.
# 2. **Точность.** 600 и 1000 точек прочитались одинаково хорошо, 18 из 18. Значит,
#    1000 точек здесь — это переплата в 2,5 раза без всякой пользы.
# 3. **Колонка «формат» — самое неожиданное.** На 300 точках модель у нас прочитала все
#    клетки **верно**, но потеряла квадратные скобки списка. Строгая проверка поставила бы
#    0 из 18, хотя ошибки чтения не было. Мелкую поломку формата функция `vytashchit_json`
#    чинит и честно пишет, что чинила. Урок: когда проверка показывает провал, сначала
#    посмотри на сырой ответ — сломалось чтение или только формат?
# 4. Совет «уменьшай картинку» — не про экономию любой ценой, а про поиск разумного
#    размера для своей задачи. Проверяют его, как всегда, замером.

# %% [markdown]
# ## Шаг 4. Модель считает фигуры
#
# Нарисуем случайное число кругов и спросим, сколько их. Правильный ответ знает код.
# Для каждого числа — две разные картинки, чтобы одна удача не обманула.

# %%
def narisovat_krugi(skolko, seed):
    sluchay = random.Random(seed)
    img = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(img)
    for _ in range(skolko):
        x, y, r = sluchay.randint(40, 760), sluchay.randint(40, 560), sluchay.randint(12, 30)
        d.ellipse((x - r, y - r, x + r, y + r), outline="black", width=3,
                  fill=sluchay.choice(["#ffd166", "#06d6a0", "#118ab2", "#ef476f"]))
    return img


VOPROS_KRUGI = 'Сколько кругов на картинке? Ответь JSON: {"krugov": число}.'
# Без схемы ответа модель на этом вопросе иногда начинает рассуждать текстом
# («To determine the number…») и не укладывается в длину — поэтому просим JSON-режим (тема 1).
print(f"{'на картинке':>12} {'модель сказала':>15}")
itog = []
for skolko in (3, 7, 12, 20):
    for seed in (1, 2):
        kartinka = narisovat_krugi(skolko, seed * 100 + skolko)
        tekst, _, _ = sprosit_pro_kartinku(VOPROS_KRUGI, v_url(kartinka, 800)[0], max_tokens=30,
                                           response_format={"type": "json_object"})
        dannye, _ = vytashchit_json(tekst)
        skazala = dannye.get("krugov") if isinstance(dannye, dict) else tekst[:20]
        ok = skazala == skolko
        itog.append(ok)
        print(f"{skolko:>12} {str(skazala):>15}  {'✅' if ok else '❌'}")
print(f"\nВерно: {sum(itog)} из {len(itog)}")
display(narisovat_krugi(20, 220))

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. На 3 кругах модель, скорее всего, права. Чем больше кругов — тем чаще ответ «почти»:
#    на один-два больше или меньше. При подготовке лаборатории 20 кругов модель посчитала
#    как 19 и как 16. Посмотри на последнюю картинку и попробуй сосчитать
#    сам — круги могут налезать друг на друга.
# 2. Заметь, что модель **не говорит «не уверена»** — она называет число так же уверенно,
#    как при правильном ответе. Это та же галлюцинация из темы 1.
# 3. Вывод из урока: не поручай модели точный счёт. Если нужен счёт — проси перечислить
#    предметы (с координатами или описанием) и считай кодом, а важное показывай человеку.

# %% [markdown]
# ## Шаг 5. Длинный документ целиком
#
# Теперь документы. Составим длинное «положение о школе» из однообразных пунктов и спрячем
# в него один факт — в начало, в середину и в конец. Документ отправим модели целиком.
#
# Школьный сервер пропускает запрос до 40 000 символов, поэтому документ будет около
# 35 000 символов. Это примерно 15–20 тысяч токенов — у нашей модели окно гораздо больше,
# так что влезет спокойно.

# %%
FAKT = "Пункт 117. Пропуск в спортзал выдаёт завуч Ольга Петровна в кабинете 115 по вторникам."
VOPROS_DOK = "Кто и где выдаёт пропуск в спортзал? Ответь одним предложением. Если в документе этого нет — скажи «нет в документе»."

SHABLONY = [
    "Пункт {n}. Ученики приходят в школу не позднее чем за 10 минут до начала первого урока.",
    "Пункт {n}. На переменах запрещается бегать по лестницам и сидеть на подоконниках.",
    "Пункт {n}. Дежурный класс следит за порядком в столовой во время большой перемены.",
    "Пункт {n}. Сменная обувь хранится в гардеробе в мешке с фамилией ученика.",
    "Пункт {n}. Библиотечные книги возвращаются не позднее последней недели учебного года.",
]


def sdelat_dokument(gde, simvolov=35_000):
    abzacy, n = [], 1
    while sum(len(a) + 1 for a in abzacy) < simvolov:
        abzacy.append(SHABLONY[n % len(SHABLONY)].format(n=n))
        n += 1
    mesto = {"начало": 1, "середина": len(abzacy) // 2, "конец": len(abzacy) - 2}[gde]
    abzacy[mesto] = FAKT
    return abzacy


def sprosit_tekst(soobshcheniya, max_tokens=80):
    otvet = client.chat.completions.create(model=MODEL, temperature=0, max_tokens=max_tokens,
                                           messages=soobshcheniya)
    return (otvet.choices[0].message.content or "").strip(), otvet.usage


def nashla(otvet):
    return "ольга" in otvet.lower() and "115" in otvet


REZULTATY = []
for gde in ("начало", "середина", "конец"):
    abzacy = sdelat_dokument(gde)
    dokument = "\n".join(abzacy)
    otvet, usage = sprosit_tekst([
        {"role": "system", "content": "Отвечай только по документу.\n\nДОКУМЕНТ:\n" + dokument},
        {"role": "user", "content": VOPROS_DOK},
    ])
    REZULTATY.append(("всё в окно", gde, usage.prompt_tokens, nashla(otvet)))
    print(f"[{gde:>8}] абзацев {len(abzacy)}, факт в абзаце {abzacy.index(FAKT) + 1}, "
          f"prompt_tokens = {usage.prompt_tokens}")
    print(f"           {'✅' if nashla(otvet) else '❌'} {otvet[:110]}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. **prompt_tokens** — тысячи токенов на **один** вопрос. Запомни число, в шаге 6
#    сравним.
# 2. Нашла ли модель факт из середины? При подготовке лаборатории нашла все три.
#    Современная модель на документе такой длины часто находит всё. «Потерянная середина» сильнее проявляется на текстах в сотни
#    тысяч токенов, а их школьный сервер не пропустит. Если у тебя все три ✅ — это
#    нормальный и честный результат. Если середина ❌ — ты увидел эффект своими глазами.
# 3. В любом случае осталась разница, которая есть всегда, — **цена**.

# %% [markdown]
# ## Шаг 6. Тот же вопрос через RAG
#
# Ищем по словам (тема 2) три самых подходящих пункта и отправляем модели только их.

# %%
def slova(tekst):
    return {s[:5] for s in re.findall(r"[а-яё]+", tekst.lower()) if len(s) > 3}


def nayti(abzacy, vopros, skolko=3):
    ocenki = sorted(abzacy, key=lambda a: len(slova(a) & slova(vopros)), reverse=True)
    return [a for a in ocenki[:skolko] if slova(a) & slova(vopros)]


for gde in ("начало", "середина", "конец"):
    abzacy = sdelat_dokument(gde)
    kuski = nayti(abzacy, VOPROS_DOK)
    otvet, usage = sprosit_tekst([
        {"role": "system", "content": "Отвечай только по документу.\n\nДОКУМЕНТ:\n" + "\n".join(kuski)},
        {"role": "user", "content": VOPROS_DOK},
    ])
    REZULTATY.append(("RAG", gde, usage.prompt_tokens, nashla(otvet)))
    print(f"[{gde:>8}] найдено кусков: {len(kuski)}, prompt_tokens = {usage.prompt_tokens}")
    for k in kuski:
        print(f"           · {k[:90]}")
    print(f"           {'✅' if nashla(otvet) else '❌'} {otvet[:110]}")

VOPROSOV_V_DEN = 500
print(f"\n{'способ':<12} {'где':>9} {'токенов':>8} {'нашла':>6} {'$ за день при ' + str(VOPROSOV_V_DEN) + ' вопросах':>30}")
for sposob, gde, tokenov, ok in REZULTATY:
    print(f"{sposob:<12} {gde:>9} {tokenov:>8} {'✅' if ok else '❌':>6} {tokenov * CENA_VHODA / 1e6 * VOPROSOV_V_DEN:>30.4f}")

v_okno = sum(t for s, _, t, _ in REZULTATY if s == "всё в окно")
v_rag = sum(t for s, _, t, _ in REZULTATY if s == "RAG")
print(f"\nВесь документ дороже RAG: {v_okno / v_rag:.0f} к 1")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. Найденные куски: пункт про спортзал должен быть среди них. Остальные два — просто
#    пункты с похожими словами. Для RAG **неважно**, где факт стоял в документе.
# 2. Итоговая таблица: у нас вышло около 11 900 токенов против 96 — весь документ
#    дороже RAG больше чем в сто раз, на каждом вопросе. Наша модель дешёвая,
#    и за день выходят центы. У сильной модели умножь на 100.
# 3. А если бы документ был в 50 раз длиннее — в окно он бы уже не влез, а RAG стоил бы
#    столько же.

# %% [markdown]
# ## Шаг 7. Вопрос другими словами
#
# Слабое место поиска по словам — вопрос, в котором нет слов из документа. Спросим
# одно и то же двумя способами.

# %%
VOPROS_INACHE = "У кого получить разрешение ходить на тренировки? Если в документе этого нет — скажи «нет в документе»."
abzacy = sdelat_dokument("середина")

kuski = nayti(abzacy, VOPROS_INACHE)
otvet_rag, _ = sprosit_tekst([
    {"role": "system", "content": "Отвечай только по документу.\n\nДОКУМЕНТ:\n" + "\n".join(kuski)},
    {"role": "user", "content": VOPROS_INACHE},
])
print(f"RAG: найдено кусков {len(kuski)}:")
for k in kuski:
    print(f"   · {k[:90]}")
print(f"   {'✅' if nashla(otvet_rag) else '❌'} {otvet_rag[:120]}\n")

otvet_okno, _ = sprosit_tekst([
    {"role": "system", "content": "Отвечай только по документу.\n\nДОКУМЕНТ:\n" + "\n".join(abzacy)},
    {"role": "user", "content": VOPROS_INACHE},
])
print(f"Всё в окно:\n   {'✅' if nashla(otvet_okno) else '❌'} {otvet_okno[:120]}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. **RAG** не нашёл ни одного куска: в вопросе нет слов «пропуск» и «спортзал».
#    Модель честно ответила «нет в документе» — хорошо, что не выдумала.
# 2. **Всё в окно** — и вот сюрприз, который случился при подготовке лаборатории: модель
#    с **полным документом тоже ответила «нет в документе»**. Весь текст был у неё перед
#    глазами, но «разрешение ходить на тренировки» она не связала с «пропуском в спортзал».
#    Правило «отвечай только по документу» сделало её осторожной: прямо такого в тексте нет.
# 3. Это важный и честный вывод: «модель видит весь документ» не значит «модель поймёт
#    любые слова». Другие слова — проблема не только поиска, но и самой модели.
#    Помогают поиск по смыслу (тема 3), просьба учитывать синонимы и, конечно, эталонный
#    набор с вопросами, заданными разными словами (тема 5).
#
# **Вариант:** замени в правиле «Отвечай только по документу» на «Отвечай по документу;
# вопрос может быть задан другими словами». Изменился ли ответ?

# %% [markdown]
# ## Попробуй сам
#
# 1. **Мелкий шрифт.** В `narisovat_raspisanie` поставь размер шрифта 14 вместо 34
#    и перезапусти шаги 2–3. С какого размера картинки начались ошибки?
# 2. **Счёт кодом.** В шаге 4 попроси модель вернуть список кругов с цветом каждого:
#    `{"krugi": [{"cvet": "..."}, ...]}` — и посчитай длину списка кодом. Стало точнее?
# 3. **Больше кусков.** В шаге 7 поставь `skolko=10` в `nayti`. Нашёл ли теперь RAG
#    нужный пункт? Сколько это стоило токенов?
# 4. **Своё фото.** Загрузи в Colab фото своего расписания (значок папки слева),
#    открой его `Image.open("имя.jpg")` и отправь с вопросом из шага 2. Проверь ответ
#    глазами — кода-проверки для чужого фото у тебя нет. Не забудь: на фото не должно
#    быть чужих лиц и фамилий.
#
# ## Что унести с собой
#
# * Картинка — это много токенов: уменьшай до разумного размера, найденного замером.
# * Крупный текст модель читает хорошо, считает — плохо и уверенно; счёт делай кодом.
# * Ответы по картинкам проверяй кодом везде, где правильный ответ можно знать.
# * Длинный документ целиком стоит в десятки раз дороже RAG на каждом вопросе.
# * RAG по словам не понимает других слов — лечится поиском по смыслу.
