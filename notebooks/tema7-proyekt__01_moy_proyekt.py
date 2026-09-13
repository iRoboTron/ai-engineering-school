# %% [markdown]
# # Лаборатория 7. Твой проект
#
# **Что это:** готовый каркас, в который нужно подставить свои документы и свои вопросы.
# Внутри собрано всё, что мы проходили: нарезка на чанки, поиск, ответ по документам
# с запретом выдумывать, проверка ответа кодом и замер качества на эталонном наборе.
#
# **Что делать:**
#
# 1. Заменить `MOI_DOKUMENTY` на свои тексты.
# 2. Заменить `MOI_ETALON` на свои вопросы — **до** того, как начнёшь что-то улучшать.
# 3. Запустить, посмотреть на число, разобрать провалы.
# 4. Улучшить одно место и замерить снова.
#
# Всё остальное уже написано.

# %%
!pip -q install rank_bm25 openai

# %%
import getpass
import os
import re
from pprint import pprint

from openai import OpenAI
from rank_bm25 import BM25Okapi

ADRES = "https://ai9.adelfos.ru/api/v1"
MODEL = "qwen/qwen3.7-flash"

try:
    from google.colab import userdata
    KOD_KLASSA = userdata.get("AI9_KOD") or os.environ.get("AI9_KOD")
except Exception:
    KOD_KLASSA = os.environ.get("AI9_KOD")

# Сервер проверит код, только когда мы обратимся к нему с ключом. Поэтому делаем один
# лёгкий запрос (список моделей) и, если код не принят, спрашиваем его заново.
client = None
while client is None:
    if not KOD_KLASSA:
        KOD_KLASSA = getpass.getpass("Код класса: ")
    client = OpenAI(base_url=ADRES, api_key=KOD_KLASSA)
    try:
        client.models.list()   # неверный код сервер не примет и ответит ошибкой
        print("Всё хорошо: код подошёл. Модель:", MODEL)
    except Exception:
        print("Код не подошёл — проверь его у учителя и введи заново.")
        client = None
        KOD_KLASSA = None      # после ошибки код из секретов и окружения больше не берём

# %% [markdown]
# ## Шаг 1. Твои документы
#
# Замени текст ниже на свой. Абзацы разделяются пустой строкой — каждый абзац станет
# отдельным чанком, поэтому старайся, чтобы один абзац был про одно.
#
# Что подойдёт: правила твоей секции, конспект по предмету, описание игры, твои заметки.
#
# ⚠️ Не бери чужую переписку, личные дела и вообще всё, что касается других людей.
# Из темы 6: то, что попало в запрос, может оказаться в ответе.

# %%
MOI_DOKUMENTY = """
Замени этот текст своим. Например, правила твоей секции по плаванию:
тренировки по понедельникам и четвергам в 17:00 в бассейне на улице Ленина.

Второй абзац — вторая тема. С собой нужны шапочка, очки и сланцы.
Абонемент на месяц стоит 2400 рублей, для членов сборной школы бесплатно.

Третий абзац. Тренер — Смирнова Анна Викторовна, телефон указан на стенде.
Пропуск занятия по болезни нужно подтвердить справкой.
"""

chanki = [k.strip().replace("\n", " ") for k in MOI_DOKUMENTY.strip().split("\n\n")]
print(f"Получилось чанков: {len(chanki)}")
for i, c in enumerate(chanki):
    print(f"  [{i}] {c[:70]}...")

# %% [markdown]
# ## Шаг 2. Твой эталонный набор
#
# **Составь его сейчас, до улучшений.** Иначе подгонишь вопросы под то, что и так
# работает, и замер потеряет смысл (тема 5).
#
# Для каждого вопроса укажи:
#
# * `nuzhen_chank` — номер чанка, который должен найтись (или `None`, если ответа нет);
# * `otvet_soderzhit` — слово или число, которое обязано быть в правильном ответе
#   (или `None` для вопросов без ответа).
#
# Минимум 8 вопросов, из них хотя бы 2 — без ответа в документах.

# %%
MOI_ETALON = [
    {"vopros": "Во сколько тренировки по плаванию?", "nuzhen_chank": 0, "otvet_soderzhit": "17:00"},
    {"vopros": "В какие дни занятия?",               "nuzhen_chank": 0, "otvet_soderzhit": "понедельник"},
    {"vopros": "Что нужно взять с собой?",           "nuzhen_chank": 1, "otvet_soderzhit": "шапочк"},
    {"vopros": "Сколько стоит абонемент?",           "nuzhen_chank": 1, "otvet_soderzhit": "2400"},
    {"vopros": "Как зовут тренера?",                 "nuzhen_chank": 2, "otvet_soderzhit": "Смирнов"},
    {"vopros": "Что делать, если пропустил по болезни?", "nuzhen_chank": 2, "otvet_soderzhit": "справк"},
    {"vopros": "Есть ли занятия в воскресенье?",     "nuzhen_chank": None, "otvet_soderzhit": None},
    {"vopros": "Сколько человек в группе?",          "nuzhen_chank": None, "otvet_soderzhit": None},
]

bez_otveta = sum(1 for z in MOI_ETALON if z["nuzhen_chank"] is None)
print(f"Вопросов: {len(MOI_ETALON)}, из них без ответа в документах: {bez_otveta}")
if bez_otveta < 2:
    print("⚠️ Добавь вопросы без ответа — иначе не заметишь, что бот начал выдумывать.")

# %% [markdown]
# ## Шаг 3. Сам бот
#
# Ниже — готовый код. Читать его полезно, менять пока не нужно.
#
# Обрати внимание на две вещи, которые взяты из прошлых тем:
#
# * `OBREZAT_DO` — обрезка слов до основы. В теме 5 это подняло качество поиска
#   с 67 % до 78 %, потому что связало «рисование» и «рисования».
# * `PRAVILO` с запретом выдумывать — грунтование из темы 2. Без него бот будет
#   уверенно сочинять, как в теме 1.

# %%
OBREZAT_DO = 6          # до скольких букв обрезаем слова; попробуй менять
SKOLKO_CHANKOV = 2      # сколько кусков кладём в запрос

PRAVILO = (
    "Ты помощник. Отвечай на вопрос ТОЛЬКО по тексту из блока ДОКУМЕНТЫ.\n"
    "Если ответа в документах нет — ответь ровно: «В документах этого нет».\n"
    "Не добавляй ничего от себя. Отвечай одним предложением."
)


def v_slova(text):
    slova = "".join(b.lower() if b.isalnum() else " " for b in text).split()
    return [s[:OBREZAT_DO] for s in slova]


poisk = BM25Okapi([v_slova(c) for c in chanki])


def nayti(vopros):
    ocenki = poisk.get_scores(v_slova(vopros))
    poryadok = sorted(range(len(chanki)), key=lambda i: ocenki[i], reverse=True)
    return [i for i in poryadok[:SKOLKO_CHANKOV] if ocenki[i] > 0]


def otvetit(vopros, pokazyvat_zapros=False):
    nomera = nayti(vopros)
    if not nomera:
        return "В документах этого нет.", []

    dokumenty = "\n".join(f"- {chanki[i]}" for i in nomera)
    zapros = [{"role": "system", "content": PRAVILO},
              {"role": "user", "content": f"ДОКУМЕНТЫ:\n{dokumenty}\n\nВОПРОС: {vopros}"}]

    # Когда бот отвечает не то, первым делом смотри не на ответ, а на запрос:
    # чаще всего виноват поиск, подсунувший не тот кусок.
    if pokazyvat_zapros:
        print("Что уходит модели:")
        pprint(zapros, width=100, sort_dicts=False)
        print()

    otvet = client.chat.completions.create(
        model=MODEL, temperature=0, max_tokens=200, messages=zapros)
    return (otvet.choices[0].message.content or "").strip(), nomera


print("Бот готов. Проверим на одном вопросе и посмотрим запрос целиком:\n")
otvet, istochniki = otvetit(MOI_ETALON[0]["vopros"], pokazyvat_zapros=True)
print(f"  ❓ {MOI_ETALON[0]['vopros']}")
print(f"  🤖 {otvet}")
print(f"  📄 источник: чанк {istochniki}")

# %% [markdown]
# ## Шаг 4. Замер: сколько ответов правильные
#
# Тот же замер, что в теме 5: отдельно поиск, отдельно ответы. Запусти и запиши число —
# это твоя точка отсчёта.

# %%
def zamer(pokazyvat_provaly=True):
    poisk_verno, otvet_verno, provaly = 0, 0, []

    for zapis in MOI_ETALON:
        nomera = nayti(zapis["vopros"])
        if zapis["nuzhen_chank"] is None:
            poisk_ok = len(nomera) == 0
        else:
            poisk_ok = zapis["nuzhen_chank"] in nomera
        poisk_verno += poisk_ok

        otvet, _ = otvetit(zapis["vopros"])
        zhdem = zapis["otvet_soderzhit"]
        if zhdem is None:
            otvet_ok = "нет" in otvet.lower() and "документ" in otvet.lower()
        else:
            otvet_ok = zhdem.lower() in otvet.lower()
        otvet_verno += otvet_ok

        if not (poisk_ok and otvet_ok):
            provaly.append((zapis["vopros"], otvet, poisk_ok, otvet_ok))

    vsego = len(MOI_ETALON)
    print(f"Поиск:  {poisk_verno} из {vsego} = {poisk_verno/vsego:.0%}")
    print(f"Ответы: {otvet_verno} из {vsego} = {otvet_verno/vsego:.0%}")

    if provaly and pokazyvat_provaly:
        print("\nПровалы — с них и начинай улучшать:")
        for vopros, otvet, poisk_ok, otvet_ok in provaly:
            vinovnik = "поиск" if not poisk_ok else "ответ модели"
            print(f"  ✗ {vopros}")
            print(f"    бот сказал: {otvet[:60]}")
            print(f"    виноват: {vinovnik}\n")
    return poisk_verno / vsego, otvet_verno / vsego


kachestvo = zamer()

# %% [markdown]
# Колонка «виноват» — самое полезное в этом выводе. Она отвечает на вопрос, который
# иначе пришлось бы гадать: чинить поиск или запрос к модели?
#
# * виноват **поиск** — нужный кусок не нашёлся. Поможет обрезка слов, другие чанки,
#   поиск по смыслу из темы 3;
# * виноват **ответ модели** — кусок нашёлся, а ответ неверный. Поможет правка `PRAVILO`
#   или другой способ нарезки.

# %% [markdown]
# ## Шаг 5. Улучшаем и проверяем
#
# Правило одно: **меняй что-то одно и замеряй на том же наборе.**
#
# Ниже — готовая проверка для первого очевидного рычага: длины обрезки слов.

# %%
VYBRANNAYA_OBREZKA = OBREZAT_DO         # запомним, что стояло до опытов

for dlina in [4, 5, 6, 8, 99]:          # 99 = фактически без обрезки
    OBREZAT_DO = dlina
    poisk = BM25Okapi([v_slova(c) for c in chanki])
    verno = 0
    for zapis in MOI_ETALON:
        nomera = nayti(zapis["vopros"])
        verno += (len(nomera) == 0) if zapis["nuzhen_chank"] is None else (zapis["nuzhen_chank"] in nomera)
    print(f"обрезка до {dlina:>2} букв: поиск {verno} из {len(MOI_ETALON)} = {verno/len(MOI_ETALON):.0%}")

# Возвращаем настройку как было: иначе дальше бот работал бы с последним значением
# из цикла (99), а отчёт в конце написал бы неправду. Такие мелочи и портят замеры.
OBREZAT_DO = VYBRANNAYA_OBREZKA
poisk = BM25Okapi([v_slova(c) for c in chanki])
print(f"\nНастройка возвращена: обрезка до {OBREZAT_DO} букв")

# %% [markdown]
# Выбери лучшее значение, впиши его в `OBREZAT_DO` в шаге 3 и перезапусти замер.
#
# Обрати внимание: слишком короткая обрезка (4 буквы) делает поиск «щедрым» — он начинает
# находить что попало, и вопросы без ответа ломаются. Слишком длинная не связывает
# словоформы. Где-то посередине оптимум — и он **зависит от твоих документов**,
# поэтому его и надо измерять, а не угадывать.

# %% [markdown]
# ## Шаг 6. Проверка ответа кодом
#
# Из темы 6: не всё нужно доверять модели. Числа из ответа обязаны встречаться
# в документах — это проверяется мгновенно и бесплатно.

# %%
def proverit_chisla(otvet, dokumenty_text):
    chisla_otveta = set(re.findall(r"\d+", otvet))
    chisla_dokumentov = set(re.findall(r"\d+", dokumenty_text))
    return chisla_otveta - chisla_dokumentov


print("Проверяем ответы бота на выдуманные числа:\n")
for zapis in MOI_ETALON:
    otvet, nomera = otvetit(zapis["vopros"])
    istochnik = " ".join(chanki[i] for i in nomera)
    lishnie = proverit_chisla(otvet, istochnik)
    if lishnie:
        print(f"  🚩 {zapis['vopros']}")
        print(f"     ответ: {otvet[:60]}")
        print(f"     чисел нет в источнике: {lishnie}\n")

print("Если выше пусто — бот не выдумал ни одного числа.")

# %% [markdown]
# ## Шаг 7. Что написать о проекте
#
# Заполни заготовку ниже честно. Из темы 7: числа сильнее прилагательных, а признание
# «вот это не работает» сильнее умолчания.

# %%
OTCHET = f"""
ЧТО Я СДЕЛАЛ
Бот отвечает на вопросы по <напиши, по каким документам>.
Документы разрезаны на {len(chanki)} чанков, поиск — BM25 с обрезкой слов
до {OBREZAT_DO} букв, ответ — модель {MODEL} с запретом отвечать не по тексту.

ЧТО ПОЛУЧИЛОСЬ
Эталонный набор: {len(MOI_ETALON)} вопросов, из них {bez_otveta} без ответа в документах.
Поиск: {kachestvo[0]:.0%} правильных. Ответы: {kachestvo[1]:.0%} правильных.
Проверка чисел кодом: <напиши, нашлись ли выдуманные числа>.

ЧТО НЕ РАБОТАЕТ
<Назови конкретный провалившийся вопрос и причину: поиск или ответ модели>

ЧТО Я ПОНЯЛ
<Одна-две честные фразы: что оказалось неожиданным, что бы сделал иначе>

ЧЕГО Я НЕ ДЕЛАЛ
Поиск по смыслу (тема 3) и векторную базу не использовал — понимаю, зачем они,
но в этом проекте их нет.
"""
print(OTCHET)

# %% [markdown]
# ## Чек-лист готовности
#
# Проект можно считать сделанным, когда выполнено всё:
#
# - [ ] Документы свои, не учебные из примера.
# - [ ] В эталонном наборе не меньше 8 вопросов, из них 2 без ответа.
# - [ ] Набор составлен **до** улучшений.
# - [ ] Качество поиска и ответов замерено, числа записаны.
# - [ ] Сделано хотя бы одно улучшение, есть замер до и после.
# - [ ] Разобран хотя бы один провал: понятно, поиск виноват или модель.
# - [ ] В отчёте честно написано, чего ты не делал.
# - [ ] В коде не осталось строчек, которые ты не можешь объяснить.
#
# Последний пункт — самый важный. Пользоваться ИИ при написании кода нормально,
# этим занимаются все. Не понимать свой код — нет: первый же вопрос «а что тут
# происходит?» покажет правду.
