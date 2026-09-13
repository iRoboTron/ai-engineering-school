# %% [markdown]
# # Лаборатория 11. Когда модель подводит
#
# **Что мы сделаем:** сначала нарочно сломаем запросы пятью разными способами и посмотрим,
# как каждая ошибка выглядит в Python. Потом соберём обёртку со всеми слоями защиты
# и проверим её на «обезьяне», которая ломает запросы нарочно.
#
# | Шаг | Что узнаем |
# |---|---|
# | 1 | Как выглядит ошибка: тип, код, текст |
# | 2 | Пять настоящих ошибок: 400, 401, 413, тайм-аут, обрезанный ответ |
# | 3 | Временная или постоянная: функция-сортировщик ошибок |
# | 4 | Повтор с растущей паузой — видим каждую попытку |
# | 5 | Обезьяна ломает запросы: проверяем повторы и резервную модель |
# | 6 | Проверка JSON и один повтор с подсказкой |
# | 7 | Понятный отказ вместо Traceback |
#
# **Что понадобится:** код класса от учителя. **Запросов:** около 35.

# %%
!pip -q install openai

# %%
import getpass
import json
import os
import random
import time

import openai
from openai import OpenAI

ADRES = "https://ai9.adelfos.ru/api/v1"
MODEL = "qwen/qwen3.7-flash"
REZERV = "google/gemma-3-12b-it"

try:
    from google.colab import userdata
    KOD_KLASSA = userdata.get("AI9_KOD")
except Exception:
    KOD_KLASSA = os.environ.get("AI9_KOD") or getpass.getpass("Код класса: ")

# max_retries=0: библиотека умеет повторять сама, но молча. Мы будем повторять сами —
# чтобы видеть каждую попытку.
client = OpenAI(base_url=ADRES, api_key=KOD_KLASSA, timeout=30, max_retries=0)
print("Подключились.")

# %% [markdown]
# ## Шаг 1. Как выглядит ошибка
#
# Когда сервер отвечает ошибкой, библиотека `openai` превращает её в **исключение** —
# особый объект, который прерывает программу, если его не поймать. У исключения есть:
#
# * **тип** — какая это ошибка (`BadRequestError`, `AuthenticationError`, …);
# * **`status_code`** — тот самый трёхзначный код от сервера;
# * **текст** — объяснение, которое прислал сервер.
#
# Сделаем функцию, которая выполняет запрос и, если он упал, красиво печатает всё это
# вместо длинного красного Traceback.

# %%
def poprobovat(nazvanie, zapros):
    """Выполняет zapros() и печатает, что вышло: ответ или разбор ошибки."""
    print(f"\n=== {nazvanie} ===")
    start = time.perf_counter()
    try:
        otvet = zapros()
        sek = time.perf_counter() - start
        vybor = otvet.choices[0]
        print(f"✅ ответ за {sek:.1f} с, finish_reason = {vybor.finish_reason}")
        print(f"   текст: {(vybor.message.content or '')[:120]!r}")
        return otvet
    except Exception as e:
        sek = time.perf_counter() - start
        print(f"❌ через {sek:.1f} с: {type(e).__name__}")
        kod = getattr(e, "status_code", None)
        if kod is not None:
            print(f"   код ответа: {kod}")
        print(f"   текст: {str(e)[:200]}")
        return e


SOOBSHCHENIYA = [{"role": "user", "content": "Назови столицу Франции одним словом."}]
poprobovat("нормальный запрос", lambda: client.chat.completions.create(model=MODEL, messages=SOOBSHCHENIYA, max_tokens=20))

# %% [markdown]
# Нормальный запрос: зелёная галочка, `finish_reason = stop`. Теперь начнём ломать.

# %% [markdown]
# ## Шаг 2. Пять настоящих ошибок
#
# Каждый эксперимент ломает запрос одним способом. Перед запуском попробуй угадать,
# какой будет код и тип ошибки.

# %%
oshibki = {}

# 1. Модель, которой нет в списке разрешённых
oshibki["неразрешённая модель"] = poprobovat(
    "1. неразрешённая модель",
    lambda: client.chat.completions.create(model="openai/gpt-6-astra", messages=SOOBSHCHENIYA, max_tokens=20))

# 2. Неверный код класса
chuzhoy = OpenAI(base_url=ADRES, api_key="neverniy-kod", max_retries=0)
oshibki["неверный код"] = poprobovat(
    "2. неверный код класса",
    lambda: chuzhoy.chat.completions.create(model=MODEL, messages=SOOBSHCHENIYA, max_tokens=20))

# 3. Слишком длинный запрос: школьный сервер принимает до 40 000 символов
ogromnyy = [{"role": "user", "content": "бла " * 12_000}]
oshibki["слишком длинный"] = poprobovat(
    "3. слишком длинный запрос",
    lambda: client.chat.completions.create(model=MODEL, messages=ogromnyy, max_tokens=20))

# %% [markdown]
# **Что посмотреть:**
#
# * **1** — код **400**, `BadRequestError`. В тексте сервер даже перечислил, какие модели можно.
# * **2** — код **401**, `AuthenticationError`: «Неверный код класса».
# * **3** — код **413**: запрос отклонён ещё до модели, деньги не потрачены.
#
# Все три — **постоянные**. Запусти ячейку ещё раз: результат будет тем же. Повторять
# такие запросы бессмысленно, их нужно исправлять.
#
# Дальше две беды, которые приходят **без кода ошибки**.

# %%
# 4. Тайм-аут: даём на ответ всего полсекунды
oshibki["тайм-аут"] = poprobovat(
    "4. тайм-аут 0.5 секунды",
    lambda: client.with_options(timeout=0.5).chat.completions.create(
        model=MODEL, max_tokens=300,
        messages=[{"role": "user", "content": "Напиши подробный рассказ о море на 200 слов."}]))

# 5. Обрезанный ответ: просим JSON и оставляем на него всего 12 токенов
obrezannyy = poprobovat(
    "5. обрезанный ответ (max_tokens=12)",
    lambda: client.chat.completions.create(
        model=MODEL, max_tokens=12,
        messages=[{"role": "user", "content":
                   'Перечисли 5 городов России в JSON: {"goroda": ["...", ...]}. Только JSON.'}]))

if not isinstance(obrezannyy, Exception):
    tekst = obrezannyy.choices[0].message.content or ""
    try:
        json.loads(tekst)
        print("   JSON разобрался")
    except json.JSONDecodeError as e:
        print(f"   JSON НЕ разобрался: {e}")

# %% [markdown]
# **Что посмотреть:**
#
# * **4** — `APITimeoutError` **без кода ответа**: сервер ничего не прислал, мы просто
#   перестали ждать. Это временная ошибка: с нормальным тайм-аутом тот же запрос пройдёт.
# * **5** — формально **успех**: зелёная галочка! Но `finish_reason = length`, и JSON
#   оборван на полуслове. Это самая коварная ошибка: программа, которая проверяет только
#   «упало или нет», покажет ученику мусор.
#
# Если в пятом эксперименте модель вдруг уложилась — уменьши `max_tokens` до 5.

# %% [markdown]
# ## Шаг 3. Временная или постоянная
#
# Соберём главное умение урока 1 в одну функцию. Она получает исключение и отвечает
# на вопрос: **есть ли смысл повторять?**

# %%
VREMENNYE_KODY = {429, 500, 502, 503, 504}


def razobrat(e):
    """Возвращает (вид, код): вид = 'временная' или 'постоянная'."""
    if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
        return "временная", "сеть/тайм-аут"
    kod = getattr(e, "status_code", None)
    if kod in VREMENNYE_KODY:
        return "временная", kod
    if kod is not None:
        return "постоянная", kod
    return "не от сервиса", type(e).__name__        # например, опечатка в нашем коде


print(f"{'эксперимент':<22} {'вид':<14} код")
for nazvanie, rezultat in oshibki.items():
    if isinstance(rezultat, Exception):
        vid, kod = razobrat(rezultat)
        print(f"{nazvanie:<22} {vid:<14} {kod}")

print(f"\n{'опечатка в коде':<22} {razobrat(NameError('x'))[0]:<14} {razobrat(NameError('x'))[1]}")

# %% [markdown]
# Посмотри на последнюю строку: `NameError` — это ошибка **в нашей программе**, а не
# у сервиса. Её нельзя ни повторять, ни прятать. Вот почему `except Exception: pass` так
# опасен — он молча проглотил бы и её.

# %% [markdown]
# ## Шаг 4. Повтор с растущей паузой
#
# Теперь обёртка, которая повторяет **только временные** ошибки: с лимитом попыток,
# растущей паузой и разбросом. Каждая попытка печатается — будем видеть, что происходит.

# %%
def s_povtorami(sdelat_zapros, popytok=4, pauza=1.0, podrobno=True):
    """sdelat_zapros() — функция без аргументов, которая делает один запрос."""
    for popytka in range(1, popytok + 1):
        start = time.perf_counter()
        try:
            otvet = sdelat_zapros()
            if podrobno:
                print(f"   попытка {popytka}: ✅ за {time.perf_counter() - start:.1f} с")
            return otvet
        except Exception as e:
            vid, kod = razobrat(e)
            if podrobno:
                print(f"   попытка {popytka}: ❌ {kod} ({vid})")
            if vid != "временная" or popytka == popytok:
                raise                                        # постоянная или попытки кончились
            zhdat = pauza * random.uniform(0.5, 1.5)
            if podrobno:
                print(f"              пауза {zhdat:.1f} с")
            time.sleep(zhdat)
            pauza *= 2


print("Постоянная ошибка — не повторяется:")
try:
    s_povtorami(lambda: client.chat.completions.create(model="openai/gpt-6-astra", messages=SOOBSHCHENIYA, max_tokens=20))
except Exception as e:
    print(f"   сдались сразу: {type(e).__name__}")

print("\nТайм-аут 0.5 с — временная, повторяется с паузами:")
try:
    s_povtorami(lambda: client.with_options(timeout=0.5).chat.completions.create(
        model=MODEL, max_tokens=300, messages=[{"role": "user", "content": "Напиши рассказ о море на 200 слов."}]),
        popytok=3)
except Exception as e:
    print(f"   попытки кончились: {type(e).__name__}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. Неразрешённая модель — **одна** попытка и сразу отказ. Никаких пауз, никаких лишних
#    запросов.
# 2. Тайм-аут — три попытки, паузы примерно 1 и 2 секунды (с разбросом). Здесь повтор
#    не помог, потому что тайм-аут у нас нарочно невозможный: полсекунды на рассказ.
#    Это тоже урок — **повторы не лечат причину**, они лишь пережидают случайность.

# %% [markdown]
# ## Шаг 5. Обезьяна ломает запросы
#
# Настоящие 503 и 429 случаются редко и не по заказу. Поэтому сделаем **обезьяну** —
# функцию, которая перед настоящим запросом с заданной вероятностью притворяется, что
# сервис ответил ошибкой. Так инженеры и проверяют защиту: ломают нарочно.

# %%
class PoddelnayaOshibka(Exception):
    """Притворяется ошибкой сервиса с кодом."""
    def __init__(self, status_code):
        super().__init__(f"поддельная ошибка {status_code}")
        self.status_code = status_code


def s_obezyanoy(model, veroyatnost, kod=503, lezhit=frozenset()):
    """Возвращает функцию-запрос, которая иногда ломается. Модели из lezhit ломаются всегда."""
    def zapros():
        if model in lezhit or random.random() < veroyatnost:
            raise PoddelnayaOshibka(kod)
        return client.chat.completions.create(model=model, max_tokens=40, messages=[
            {"role": "user", "content": "Скажи одним предложением, зачем нужна перемена."}])
    return zapros


random.seed(1)
print("Обезьяна ломает 50% запросов, 5 вопросов подряд:\n")
for nomer in range(1, 6):
    print(f"Вопрос {nomer}:")
    try:
        otvet = s_povtorami(s_obezyanoy(MODEL, 0.5), popytok=4, pauza=0.5)
        print(f"   → {otvet.choices[0].message.content.strip()[:80]}")
    except Exception as e:
        print(f"   → не получилось: {e}")

# %% [markdown]
# Посмотри на попытки: у одних вопросов сразу ✅, у других — одна-две неудачи, пауза
# и успех. Ученик при этом просто ждал чуть дольше и получил ответ.
#
# А теперь хуже: **основная модель легла совсем**. Повторы тут бессильны — добавим
# резервную модель.

# %%
def nadezhno(sdelat_dlya_modeli, modeli, podrobno=True):
    """Пробует модели по очереди, каждую — с повторами. Возвращает (ответ, модель)."""
    poslednyaya_oshibka = None
    for model in modeli:
        if podrobno:
            print(f"  модель {model}:")
        try:
            return s_povtorami(sdelat_dlya_modeli(model), popytok=3, pauza=0.5, podrobno=podrobno), model
        except Exception as e:
            poslednyaya_oshibka = e
            if razobrat(e)[0] == "постоянная":
                raise                              # другая модель постоянную ошибку не исправит
    raise poslednyaya_oshibka


random.seed(2)
LEZHIT = {MODEL}
print(f"Основная модель {MODEL} не отвечает. Резервная — {REZERV}.\n")
try:
    otvet, kto = nadezhno(lambda m: s_obezyanoy(m, 0.2, lezhit=LEZHIT), [MODEL, REZERV])
    print(f"\n→ ответила {kto} (сервер сообщил: {otvet.model}): {otvet.choices[0].message.content.strip()[:80]}")
except Exception as e:
    print(f"\n→ не получилось: {e}")

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. Основная модель — три попытки, все ❌ 503, паузы растут. Потом обёртка **сдаётся
#    и переходит к резервной**.
# 2. Резервная отвечает (иногда после одной неудачи — обезьяна ломает и её на 20%).
# 3. В последней строке видно, **какая модель ответила на самом деле**. В настоящем боте
#    это обязательно пишут в журнал (тема 8): иначе не понять, почему ответы вдруг стали
#    другими.
#
# **Вариант:** добавь `REZERV` в `LEZHIT`. Что вернёт обёртка, когда легли обе?

# %% [markdown]
# ## Шаг 6. Проверка JSON и один повтор с подсказкой
#
# Ответ пришёл — это ещё не значит, что он годный. Сделаем функцию, которая:
#
# 1. проверяет `finish_reason` и разбирает JSON;
# 2. если не вышло — **один раз** повторяет, добавив подсказку, что было не так;
# 3. если и второй не годен — сдаётся.
#
# Чтобы увидеть повтор, первую попытку нарочно сделаем с маленьким `max_tokens`.

# %%
def poluchit_json(vopros, polya, pervyy_max_tokens=15):
    soobshcheniya = [
        {"role": "system", "content": f"Отвечай строго JSON без текста вокруг. Поля: {', '.join(polya)}."},
        {"role": "user", "content": vopros},
    ]
    for popytka, max_tokens in ((1, pervyy_max_tokens), (2, 200)):
        otvet = client.chat.completions.create(model=MODEL, temperature=0, max_tokens=max_tokens,
                                               messages=soobshcheniya)
        vybor = otvet.choices[0]
        tekst = vybor.message.content or ""
        print(f"попытка {popytka} (max_tokens={max_tokens}): finish_reason={vybor.finish_reason}")
        print(f"   текст: {tekst[:120]!r}")

        problema = None
        if vybor.finish_reason == "length":
            problema = "ответ оборвался: не уложился в длину"
        else:
            try:
                dannye = json.loads(tekst)
                nedostayet = [p for p in polya if p not in dannye]
                if nedostayet:
                    problema = f"в JSON нет полей: {nedostayet}"
                else:
                    print("   ✅ JSON годный:", dannye)
                    return dannye
            except json.JSONDecodeError:
                problema = "это не JSON"
        print(f"   ❌ {problema}")
        # Подсказка для повтора: показываем модели её ответ и что с ним не так.
        soobshcheniya += [
            {"role": "assistant", "content": tekst},
            {"role": "user", "content": f"Твой ответ не годится: {problema}. Ответь короче, строго JSON с полями {polya}."},
        ]
    raise ValueError("Модель дважды вернула негодный JSON")


rezultat = poluchit_json("Какая самая высокая гора в мире и какова её высота в метрах?", ["gora", "vysota"])

# %% [markdown]
# **Что посмотреть в выводе:**
#
# 1. Попытка 1 почти наверняка оборвалась (`length`) — мы так и задумали.
# 2. Попытка 2 получила **подсказку** — модель видит свой прошлый ответ и что с ним не так.
# 3. Годный JSON проверен кодом: разобрался, и нужные поля на месте.
#
# Почему только один повтор: если модель дважды не справилась с форматом, третий раз
# обычно ничего не меняет, а деньги и время тратятся. Дальше — резервная модель или
# честный отказ.

# %% [markdown]
# ## Шаг 7. Понятный отказ
#
# Последний слой: что увидит ученик, если не помогло ничего. Превратим каждую ошибку
# из шага 2 в человеческое сообщение.

# %%
def ponyatno(e):
    kod = getattr(e, "status_code", None)
    if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
        return "Сервис долго не отвечает. Попробуй ещё раз через минуту."
    if kod == 401:
        return "Неверный код класса. Проверь его у учителя."
    if kod == 413:
        return "Вопрос слишком длинный. Сократи его или раздели на части."
    if kod == 429:
        return "Слишком много вопросов за короткое время. Подожди немного."
    if kod in (500, 502, 503, 504):
        return "Сервис сейчас перегружен. Попробуй через минуту."
    if kod == 400:
        return "Бот не смог обработать этот запрос. Сообщи учителю — это ошибка в настройках."
    return "Что-то пошло не так. Попробуй позже."


print(f"{'что сломалось':<22} что увидит ученик")
for nazvanie, rezultat in oshibki.items():
    if isinstance(rezultat, Exception):
        print(f"{nazvanie:<22} {ponyatno(rezultat)}")
print(f"{'перегрузка (503)':<22} {ponyatno(PoddelnayaOshibka(503))}")

# %% [markdown]
# Сравни с тем, что было бы без этого слоя: `openai.AuthenticationError: Error code: 401 -
# {'detail': 'Неверный код класса...'}`. Для ученика это непонятный красный текст.
#
# Обрати внимание на сообщение для 400: ученик в нём не виноват — запрос составил
# **программист**. Поэтому честно говорим, что это ошибка настройки, и просим сообщить.

# %% [markdown]
# ## Попробуй сам
#
# 1. **Выключатель.** Сделай счётчик: если основная модель три раза подряд отказала
#    с 503, следующие вопросы сразу отправляй резервной, не тратя попытки. Проверь на
#    обезьяне из шага 5 с `lezhit={MODEL}`.
# 2. **Пауза из ответа сервера.** Если ошибка 429 и в тексте есть «лимит … в час»,
#    повторять через секунду бессмысленно. Сделай, чтобы `s_povtorami` в этом случае
#    сразу сдавалась с понятным сообщением.
# 3. **Всё вместе.** Собери функцию `otvetit(vopros)`: резервная модель + повторы +
#    проверка `finish_reason` + понятный отказ. Прогони её на обезьяне с вероятностью 0.7.
#    Какая доля вопросов дошла до ученика?
#
# ## Что унести с собой
#
# * Ошибка в Python — исключение с типом, кодом и текстом; смотри на все три.
# * 400, 401, 413 — постоянные: исправлять, а не повторять.
# * 429, 5xx, тайм-аут — временные: пауза растёт, попыток немного, у паузы разброс.
# * Код 200 не значит «годно»: проверяй `finish_reason` и формат ответа кодом.
# * Когда основная модель легла — резервная, и запись в журнал, кто ответил.
# * Если не помогло ничего — понятное сообщение, а не Traceback.
