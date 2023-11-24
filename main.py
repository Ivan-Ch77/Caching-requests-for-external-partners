import redis
from fastapi import FastAPI, Request
from pydantic import BaseModel, HttpUrl
import httpx
import json
import logging
import os

from starlette.responses import JSONResponse

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Подключение к Redis
redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = os.getenv("REDIS_PORT", 6379)
redis_db = os.getenv("REDIS_DB", 0)
cache = redis.Redis(host=redis_host, port=redis_port, db=redis_db)

app = FastAPI()

class ProxyRequest(BaseModel):
    url: HttpUrl
    method: str
    body: dict = None

@app.api_route("/proxy/", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request):
    try:
        body = await request.json() if request.method != "GET" else None
        method = request.method
        url = request.query_params.get("url")  # Получаем URL из параметров запроса

        # Создаем ключ кэша
        cache_key = json.dumps({"method": method, "url": url, "body": body})

        # Проверяем, есть ли ответ в кэше
        cached_response = cache.get(cache_key)
        if cached_response:
            return json.loads(cached_response)

        # Если нет, делаем запрос
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=body)
                cache.set(cache_key, json.dumps(response.json()))
                return response.json()
            except httpx.HTTPStatusError as e:
                # Сохраняем ошибку в кэше
                error_response = {"status_code": e.response.status_code, "detail": str(e)}
                cache.set(cache_key, json.dumps(error_response))
                return error_response
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}")
        return {"error": "Внутренняя ошибка сервера"}

@app.get("/cached-requests/")
async def get_cached_requests():
    keys = cache.keys("*")
    cached_requests = {}
    for key in keys:
        cached_requests[key.decode("utf-8")] = json.loads(cache.get(key))
    return cached_requests