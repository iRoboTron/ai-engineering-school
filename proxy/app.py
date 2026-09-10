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
import time
from collections import deque
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    """Есть ли в ответе непустой текст.

    Некоторые модели «размышляют» и иногда возвращают пустое поле content.
    Для урока это то же самое, что отказ: ученик видит пустоту и не понимает, почему.
    Поэтому такой ответ считаем неудачным и пробуем следующую модель.
    """
    if not response.headers.get("content-type", "").startswith("application/json"):
        return False
    try:
        vybory = response.json().get("choices") or []
        return bool((vybory[0].get("message", {}).get("content") or "").strip())
    except (ValueError, IndexError, AttributeError):
        return False


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


@app.get("/api/v1/models")
async def models(authorization: str = Header(None), x_class_token: str = Header(None)):
    _check_token(authorization, x_class_token)
    return {"object": "list", "data": [{"id": name, "object": "model"} for name in sorted(ALLOWED_MODELS)]}


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
    payload.pop("stream", None)  # поток не поддерживаем: в ноутбуках он не нужен

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
