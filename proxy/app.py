"""Прослойка между учениками и OpenRouter.

Зачем она нужна:
  * ключ OpenRouter лежит только здесь, на сервере, — у детей его нет и быть не должно;
  * OpenRouter не отвечает на запросы из РФ, а этот сервер отвечает;
  * можно ограничить расходы: список разрешённых моделей, лимит длины ответа,
    ограничение числа запросов на класс и на день.

Наружу отдаёт тот же формат, что и OpenAI/OpenRouter, поэтому в ноутбуках работает
обычный клиент `openai` — достаточно указать base_url и «ключ» = код класса.
"""
import asyncio
import json
import os
import re
import time
from collections import deque
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

# --- НАСТРОЙКИ (задаются в /etc/ai9-proxy.env) ---
OPENROUTER_KEY = os.environ["OPENROUTER_API_KEY"]
CLASS_TOKENS = {t.strip() for t in os.environ.get("AI9_CLASS_TOKENS", "").split(",") if t.strip()}
UPSTREAM = os.environ.get("AI9_UPSTREAM", "https://openrouter.ai/api/v1")
LOG_PATH = Path(os.environ.get("AI9_LOG", "/var/log/ai9-proxy/usage.jsonl"))

# Разрешённые модели.
#
# Почему не бесплатные (:free): они общие на всех пользователей OpenRouter, поэтому
# на втором-третьем запросе подряд отвечают «слишком много запросов», а часть из них
# подмешивает в ответ собственные размышления («We need to output only the name...»)
# и обрывается на полуслове. Для урока это негодно.
#
# Эти четыре — дешёвые платные: отвечают коротко и по делу, знают русский, умеют
# вызов инструментов (тема 4) и структурированный ответ (тема 1). Выход стоит
# 0,03–0,15 доллара за миллион токенов: полный прогон всех лабораторных классом
# из 30 человек обходится примерно в четверть доллара.
#
# Список меняется у самого OpenRouter, поэтому его можно переопределить переменной
# AI9_MODELS в /etc/ai9-proxy.env, не трогая код.
MODELI_PO_UMOLCHANIYU = (
    "qwen/qwen3.7-flash,"
    "google/gemma-3-12b-it,"
    "mistralai/mistral-nemo,"
    "inception/mercury-2.5"
)
ALLOWED_MODELS = {m.strip() for m in os.environ.get("AI9_MODELS", MODELI_PO_UMOLCHANIYU).split(",") if m.strip()}
# По умолчанию — та, что на проверке отвечала по-русски точнее и короче остальных.
_DEFAULT = "qwen/qwen3.7-flash"
DEFAULT_MODEL = os.environ.get("AI9_DEFAULT_MODEL", _DEFAULT if _DEFAULT in ALLOWED_MODELS else sorted(ALLOWED_MODELS)[0])

MAX_TOKENS_CAP = int(os.environ.get("AI9_MAX_TOKENS", "1024"))   # потолок длины ответа
MAX_INPUT_CHARS = int(os.environ.get("AI9_MAX_INPUT", "40000"))  # потолок длины запроса
PER_TOKEN_PER_HOUR = int(os.environ.get("AI9_RATE_HOUR", "120"))  # запросов в час на класс
GLOBAL_PER_DAY = int(os.environ.get("AI9_RATE_DAY", "3000"))      # запросов в сутки всего

app = FastAPI(title="ai9 proxy", docs_url=None, redoc_url=None)

# Ноутбуки ходят с сервера, но интерактивные демо на сайте — из браузера.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ai9.adelfos.ru"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

_hits = {}          # код класса -> отметки времени запросов за последний час
_day = deque()      # отметки времени всех запросов за последние сутки


def _rate_limit(token):
    """Простое ограничение частоты в памяти процесса: на класс в час и на всех в сутки."""
    now = time.time()

    marks = _hits.setdefault(token, deque())
    while marks and now - marks[0] > 3600:
        marks.popleft()
    if len(marks) >= PER_TOKEN_PER_HOUR:
        raise HTTPException(429, f"Слишком много запросов от этого класса: лимит {PER_TOKEN_PER_HOUR} в час. Подождите немного.")

    while _day and now - _day[0] > 86400:
        _day.popleft()
    if len(_day) >= GLOBAL_PER_DAY:
        raise HTTPException(429, "Дневной лимит запросов исчерпан. Попробуйте завтра.")

    marks.append(now)
    _day.append(now)


def _log(record):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # сломанный лог не должен ронять урок


def _est_otvet(response):
    """Есть ли в ответе непустой текст или просьба вызвать инструмент.

    Некоторые модели «размышляют» и иногда возвращают пустое поле content.
    Для урока это то же самое, что отказ: ученик видит пустоту и не понимает, почему.
    Поэтому такой ответ считаем неудачным и пробуем следующую модель.
    """
    if not response.headers.get("content-type", "").startswith("application/json"):
        return False
    try:
        soobshchenie = (response.json().get("choices") or [])[0].get("message", {})
    except (ValueError, IndexError, AttributeError):
        return False
    # Ответ считается нормальным, если есть текст ЛИБО просьба вызвать инструмент:
    # при вызове инструмента content пустой по определению, и это не ошибка.
    if soobshchenie.get("tool_calls"):
        return True
    return bool((soobshchenie.get("content") or "").strip())


def _check_token(authorization, x_class_token):
    """Код класса принимаем и как обычный ключ (Authorization), и отдельным заголовком."""
    token = (x_class_token or "").strip()
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not CLASS_TOKENS:
        raise HTTPException(500, "На сервере не задан ни один код класса")
    if token not in CLASS_TOKENS:
        raise HTTPException(401, "Неверный код класса. Возьмите правильный у учителя.")
    return token


@app.get("/api/health")
async def health():
    return {"status": "ok", "models": sorted(ALLOWED_MODELS), "default_model": DEFAULT_MODEL}


# --- Витрина моделей (docs/books/models.html) ---
# Каталог OpenRouter публичный, но из РФ браузер до него не достучится — поэтому
# сервер забирает его сам, раз в час, и отдаёт только нужные странице поля.
#
# Рейтинг — открытый датасет LMArena (CC BY 4.0) на Hugging Face: люди вслепую
# сравнивают ответы двух моделей. Берём общий зачёт и отдельный зачёт на русском.
# Названия у LMArena свои, поэтому сопоставляем их с id OpenRouter по нормализованному
# имени; приблизительные совпадения помечаем, чтобы их было видно на странице.
CATALOG_TTL = int(os.environ.get("AI9_CATALOG_TTL", "3600"))
ARENA_TTL = int(os.environ.get("AI9_ARENA_TTL", str(12 * 3600)))
ARENA_URL = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/main/text/latest-00000-of-00001.parquet"
# Зачёты LMArena, которые отдаём наружу: ключ в ответе API -> категория в датасете.
ARENA_CATEGORIES = {
    "overall": "overall", "russian": "russian", "coding": "coding", "math": "math",
    "instructions": "instruction_following", "hard": "hard_prompts",
    "creative": "creative_writing", "multi_turn": "multi_turn",
}

_catalog = {"data": None, "fetched_at": 0.0}
_catalog_lock = asyncio.Lock()
_arena = {"tables": {}, "published": None, "fetched_at": 0.0, "task": None, "error": None}

_EFFORT = re.compile(r"(-(x?high|medium|low|minimal|thinking(-\d+k)?|reasoning|no-thinking|instant))+$")


def _norm(name):
    """Приводит id OpenRouter и имя LMArena к общему виду: gemini-3.8-flash-high -> gemini-3-8-flash.

    Полные даты (20251101) убираем — это та же модель. Короткие снимки версий (2512, 02-23)
    оставляем: mistral-large-2512 и mistral-large-2407 — разные модели.
    """
    s = name.lower().split("/")[-1].split(":")[0]
    s = re.sub(r"\s*\(.*?\)", "", s).strip()
    s = s.replace(".", "-").replace("_", "-").replace(" ", "-")
    s = re.sub(r"-(\d{8}|\d{4}-\d{2}-\d{2})(?=-|$)", "", s)
    for _ in range(2):
        s = re.sub(r"-(it|preview|exp|latest|chat-latest)$", "", s)
        s = _EFFORT.sub("", s)
    return s


def _loose(key):
    """Без короткого снимка версии — только для приблизительного совпадения."""
    return re.sub(r"-(\d{4}|\d{2}-\d{2}|\d{2}-\d{4})$", "", key)


def _parse_arena(blob):
    """Parquet -> {зачёт: (точные имена, приблизительные)}. Работает в потоке: pyarrow синхронный."""
    import io
    import pyarrow.parquet as pq

    rows = pq.read_table(io.BytesIO(blob), columns=[
        "model_name", "rating", "vote_count", "category", "leaderboard_publish_date"]).to_pylist()
    wanted = {v: k for k, v in ARENA_CATEGORIES.items()}
    tables = {k: ({}, {}) for k in ARENA_CATEGORIES}
    for row in rows:
        name = wanted.get(row["category"])
        if name is None:
            continue
        strict, loose = tables[name]
        key = _norm(row["model_name"])
        # У LMArena одна модель встречается с разными режимами рассуждения — берём лучший.
        for table, k in ((strict, key), (loose, _loose(key))):
            if k not in table or row["rating"] > table[k]["rating"]:
                table[k] = row
    published = max((r["leaderboard_publish_date"] for r in rows), default=None)
    return tables, published


async def _refresh_arena():
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(ARENA_URL)
            r.raise_for_status()
        _arena["tables"], _arena["published"] = await asyncio.to_thread(_parse_arena, r.content)
        _arena["fetched_at"] = time.time()
        _arena["error"] = None
    except Exception as e:   # битый файл или сеть — витрина работает и без рейтинга
        _arena["error"] = f"LMArena недоступна: {type(e).__name__}"
        _arena["fetched_at"] = time.time() - ARENA_TTL + 300   # повторим через 5 минут, не на каждый запрос
    finally:
        _arena["task"] = None


def _arena_lookup(tables, model_id):
    strict, loose = tables
    key = _norm(model_id)
    if key in strict:
        return strict[key], True
    # Приблизительно: другой снимок той же линейки (mistral-large-2512 ≈ mistral-large-2407)
    # или у LMArena есть только максимальный режим (claude-fable-5.1 ≈ claude-fable-5.1-max).
    if _loose(key) in loose:
        return loose[_loose(key)], False
    for suffix in ("-max", "-high"):
        if key + suffix in strict:
            return strict[key + suffix], False
    return None, False


def _catalog_row(m):
    pricing = m.get("pricing") or {}
    arch = m.get("architecture") or {}
    return {
        "id": m.get("id"),
        "name": m.get("name"),
        "created": m.get("created"),
        "context_length": m.get("context_length"),
        "prompt": pricing.get("prompt"),
        "completion": pricing.get("completion"),
        "params": m.get("supported_parameters") or [],
        "input": arch.get("input_modalities") or [],
        "output": arch.get("output_modalities") or [],
        "expiration_date": m.get("expiration_date"),
    }


def _with_rating(row):
    """Добавляет рейтинги: ratings = {зачёт: {rating, votes}}, плюс имя у LMArena и точность совпадения."""
    out = dict(row, ratings={}, arena_name=None, arena_exact=None)
    for category, tables in _arena["tables"].items():
        hit, exact = _arena_lookup(tables, row["id"])
        if hit:
            out["ratings"][category] = {"rating": round(hit["rating"]), "votes": int(hit["vote_count"])}
            if out["arena_name"] is None or category == "overall":
                out["arena_name"], out["arena_exact"] = hit["model_name"], exact
    return out


@app.get("/api/catalog")
async def catalog():
    async with _catalog_lock:
        stale = False
        if _catalog["data"] is None or time.time() - _catalog["fetched_at"] > CATALOG_TTL:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.get(f"{UPSTREAM}/models")
                    r.raise_for_status()
                    _catalog["data"] = [_catalog_row(m) for m in r.json()["data"]]
                    _catalog["fetched_at"] = time.time()
            except (httpx.HTTPError, KeyError, ValueError):
                if _catalog["data"] is None:
                    raise HTTPException(502, "OpenRouter не отдал каталог моделей, попробуй позже")
                stale = True   # отдаём прошлый удачный каталог, но честно помечаем
        # Рейтинг качается и разбирается в фоне: страница не ждёт, а спросит ещё раз.
        if time.time() - _arena["fetched_at"] > ARENA_TTL and _arena["task"] is None:
            _arena["task"] = asyncio.create_task(_refresh_arena())
    return {
        "fetched_at": _catalog["fetched_at"],
        "stale": stale,
        "allowed": sorted(ALLOWED_MODELS),
        "default_model": DEFAULT_MODEL,
        "arena": {
            "source": "LMArena, CC BY 4.0",
            "categories": list(ARENA_CATEGORIES),
            "published": _arena["published"],
            "loading": _arena["task"] is not None,
            "error": _arena["error"],
        },
        "models": [_with_rating(m) for m in _catalog["data"]],
    }


@app.get("/api/v1/models")
async def models(authorization: str = Header(None), x_class_token: str = Header(None)):
    _check_token(authorization, x_class_token)
    return {"object": "list", "data": [{"id": name, "object": "model"} for name in sorted(ALLOWED_MODELS)]}


UPSTREAM_HEADERS = {
    "HTTP-Referer": "https://ai9.adelfos.ru",
    "X-Title": "AI dlya 9 klassa",
}


async def _chat_stream(payload, token, model):
    """Потоковый ответ (тема 10): куски текста пересылаются ученику по мере появления.

    Резервная модель работает так же, как без потока, но только до первого байта:
    если модель отказала сразу — берём следующую; если поток уже пошёл — назад дороги нет.
    """
    payload["stream_options"] = {"include_usage": True}
    poryadok = [model] + [m for m in sorted(ALLOWED_MODELS) if m != model]
    client = httpx.AsyncClient(timeout=120)
    started = time.time()
    for kandidat in poryadok:
        payload["model"] = kandidat
        request = client.build_request(
            "POST", f"{UPSTREAM}/chat/completions", json=payload,
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}", **UPSTREAM_HEADERS},
        )
        try:
            response = await client.send(request, stream=True)
        except httpx.RequestError as error:
            _log({"ts": time.time(), "token": token, "model": kandidat, "stream": True, "error": str(error)})
            continue
        if response.status_code in {429, 500, 502, 503, 504}:
            await response.aclose()
            _log({"ts": time.time(), "token": token, "model": kandidat, "stream": True,
                  "status": response.status_code, "note": "временный отказ, пробуем следующую"})
            continue

        async def peredat(response=response, kandidat=kandidat):
            usage = {}
            try:
                async for line in response.aiter_lines():
                    if line.startswith("data: {") and '"usage"' in line:
                        try:
                            usage = json.loads(line[6:]).get("usage") or usage
                        except ValueError:
                            pass
                    yield (line + "\n").encode()
            finally:
                await response.aclose()
                await client.aclose()
                _log({"ts": time.time(), "token": token, "model": kandidat, "zaprosheno": model,
                      "stream": True, "status": response.status_code,
                      "seconds": round(time.time() - started, 2),
                      "prompt_tokens": usage.get("prompt_tokens"),
                      "completion_tokens": usage.get("completion_tokens")})

        return StreamingResponse(
            peredat(), status_code=response.status_code,
            media_type=response.headers.get("content-type", "text/event-stream"),
            headers={"X-AI9-Model": kandidat, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    await client.aclose()
    raise HTTPException(502, "Ни одна модель сейчас не отвечает. Попробуйте через минуту.")


@app.post("/api/v1/chat/completions")
async def chat(request: Request, authorization: str = Header(None), x_class_token: str = Header(None)):
    token = _check_token(authorization, x_class_token)
    _rate_limit(token)

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Тело запроса не является JSON")

    model = payload.get("model") or DEFAULT_MODEL
    if model not in ALLOWED_MODELS:
        raise HTTPException(
            400,
            f"Модель {model!r} не разрешена. Доступны: {', '.join(sorted(ALLOWED_MODELS))}",
        )

    size = len(json.dumps(payload.get("messages", []), ensure_ascii=False))
    if size > MAX_INPUT_CHARS:
        raise HTTPException(413, f"Запрос слишком длинный: {size} символов, максимум {MAX_INPUT_CHARS}")

    payload["model"] = model
    payload["max_tokens"] = min(int(payload.get("max_tokens") or MAX_TOKENS_CAP), MAX_TOKENS_CAP)
    if payload.get("stream"):
        return await _chat_stream(payload, token, model)

    # Бесплатные модели у поставщиков общие на всех, поэтому они регулярно отвечают
    # «слишком много запросов». Для урока это смертельно: лаба делает подряд несколько
    # запросов и обрывается на середине. Поэтому при отказе пробуем следующую модель
    # из списка — ученик этого даже не замечает, а какая модель ответила на самом деле,
    # видно в заголовке ответа.
    poryadok = [model] + [m for m in sorted(ALLOWED_MODELS) if m != model]
    VREMENNYE_OTKAZY = {429, 500, 502, 503, 504}

    started = time.time()
    response = None
    async with httpx.AsyncClient(timeout=120) as client:
        for popytka, kandidat in enumerate(poryadok):
            payload["model"] = kandidat
            try:
                response = await client.post(
                    f"{UPSTREAM}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "HTTP-Referer": "https://ai9.adelfos.ru",
                        "X-Title": "AI dlya 9 klassa",
                    },
                    json=payload,
                )
            except httpx.RequestError as error:
                _log({"ts": time.time(), "token": token, "model": kandidat, "error": str(error)})
                continue

            if response.status_code not in VREMENNYE_OTKAZY and _est_otvet(response):
                break
            _log({"ts": time.time(), "token": token, "model": kandidat,
                  "status": response.status_code, "note": "временный отказ, пробуем следующую"})
            if popytka == 0:
                await asyncio.sleep(1.5)   # первой модели даём второй шанс после паузы

    if response is None or not _est_otvet(response):
        # Все кандидаты отказали или вернули пустоту. Отдаём понятную ошибку,
        # а не сломанный ответ: иначе ученик получит невнятное падение в ноутбуке.
        _log({"ts": time.time(), "token": token, "model": model, "note": "все модели отказали"})
        raise HTTPException(502, "Ни одна модель сейчас не отвечает. Попробуйте через минуту.")

    ispolzovana = payload["model"]
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    usage = body.get("usage", {}) if isinstance(body, dict) else {}
    _log({
        "ts": time.time(),
        "token": token,
        "model": ispolzovana,
        "zaprosheno": model,
        "status": response.status_code,
        "seconds": round(time.time() - started, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    })

    return JSONResponse(
        body or {"error": {"message": response.text[:500]}},
        status_code=response.status_code,
        headers={"X-AI9-Model": ispolzovana},
    )
