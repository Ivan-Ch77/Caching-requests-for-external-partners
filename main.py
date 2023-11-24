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
    '''
    Представление для кэширования ответов на http запросы

    '''
    try:
        method = request.method                                                                                         # Получаем метод запроса
        if method != "GET":
            body = await request.json()                                                                                 # Получаем тело запроса, если это не GET-запрос
        else:
            body = None                                                                                                 # Иначе присваиваем null значение
        url = request.query_params.get("url")                                                                           # Получаем URL из параметров запроса

        # Создаем ключ кэша
        key = json.dumps({"method": method, "url": url, "body": body})

        # По созданному ключу проверяем, есть ли ответ в кэше
        response = cache.get(key)
        if response:
            return json.loads(response)

        # Если нет, делаем запрос
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(method, url, json=body)                                                 # Получаем ответ по запросу
                cache.set(key, json.dumps(response.json()))                                                             # Сохраняем ответ по ключу
                return response.json()
            except httpx.HTTPStatusError as e:
                error_response = {"status_code": e.response.status_code, "detail": str(e)}                              # Сохраняем ошибку в кэше
                cache.set(key, json.dumps(error_response))
                return error_response
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}")
        return {"error": "Внутренняя ошибка сервера"}

@app.get("/cached-requests/")
async def get_cached_requests():
    '''
    Представление для получения всех сохраненных http запросов
    :return:
    '''
    keys = cache.keys("*")
    requests = {}
    for key in keys:
        requests[key.decode("utf-8")] = json.loads(cache.get(key))
    return requests