import aioredis
from fastapi import FastAPI, Request
import httpx
import json
import logging
import os
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse
from urllib.parse import urlparse


app = FastAPI()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройка Jinja2
templates = Jinja2Templates(directory="templates")

# Установка соединения с Redis
async def get_redis():
    return await aioredis.from_url('redis://localhost:6379')

def extract_subdomain(url: str) -> str:
    parsed_url = urlparse(url)
    path = parsed_url.path
    # Разделяем путь на части и берем первую часть после основного домена
    subdomain = path.split('/')[1] if path.startswith('/') else path.split('/')[0]
    return subdomain

@app.api_route("/proxy/", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request):
    # Подключение к Redis
    redis = await get_redis()
    try:
        method = request.method
        if method != "GET":
            body = await request.json()
        else:
            body = None
        url = request.query_params.get("url")
        # Извлекаем поддомен
        subdomain = extract_subdomain(str(url))

        key = json.dumps({"method": method, "url": url, "body": body, "subdomain": subdomain})

        cached_response = await redis.get(key)
        if cached_response:
            return json.loads(cached_response)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=body)
                await redis.set(key, json.dumps(response.json()))
                return response.json()
            except httpx.HTTPStatusError as e:
                error_response = {"status_code": e.response.status_code, "detail": str(e)}
                await redis.set(key, json.dumps(error_response))
                return error_response
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}")
        return {"error": "Внутренняя ошибка сервера"}
    finally:
        # Закрываем соединение с Redis
        await redis.close()

@app.get("/cached-requests/", response_class=HTMLResponse)
async def get_cached_requests(request: Request):
    redis = await get_redis()
    keys = await redis.keys("*")
    requests = []
    for key in keys:
        cached_response = await redis.get(key)
        requests.append({
            "key": key.decode("utf-8"),
            "response": json.loads(cached_response)
        })
    # Отправляем данные в шаблон и возвращаем HTML-ответ
    return templates.TemplateResponse("cached_requests.html", {"request": request, "requests": requests})


