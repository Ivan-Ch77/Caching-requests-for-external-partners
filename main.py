import hashlib
import json

from fastapi.responses import HTMLResponse
from fastapi import FastAPI, HTTPException
from fastapi.templating import Jinja2Templates
import aioredis
import aiohttp

from fastapi import FastAPI, Request
import httpx
import logging
import os

from urllib.parse import urlparse
import xmltodict

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
        content_type = request.headers.get('Content-Type')
        if method != "GET":
            if content_type == "application/json":
                body = await request.json()
            elif content_type == "application/xml":
                body = await request.body()
                body = xmltodict.parse(body.decode("utf-8"))
            else:
                # Другие типы
                body = None
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
                if content_type == "application/json":
                    response = await client.request(method, url, json=body)
                    await redis.set(key, json.dumps(response.json()))
                    return response.json()
                elif content_type == "application/xml":
                    response = await client.request(method, url, data=xmltodict.unparse(body))
                    await redis.set(key, response.text)
                    return response.text
                else:
                    response = await client.request(method, url)


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
        try:
            # Пытаемся декодировать как JSON
            response_data = json.loads(cached_response)
        except json.JSONDecodeError:
            # Если не получается, предполагаем, что это текст или XML
            response_data = cached_response.decode("utf-8")

        requests.append({
            "key": key.decode("utf-8"),
            "response": response_data
        })
    # Отправляем данные в шаблон и возвращаем HTML-ответ
    return templates.TemplateResponse("cached_requests.html", {"request": request, "requests": requests})


# # Обработчик запросов к прокси-серверу
# @app.put("/proxy")
# async def proxy(request_data: dict):
#     # Подключение к Redis
#     redis = await get_redis()

#     # Создание уникального ключа кэша на основе хеша JSON-представления запроса
#     request_json = json.dumps(request_data, sort_keys=True)
#     cache_key = hashlib.sha256(request_json.encode()).hexdigest()
#     print(cache_key)

#     try:
#         # Проверка, есть ли данные в кэше
#         cached_data = await redis.get(cache_key)
#         if cached_data:
#             print('Данные есть в кэше, отправляем заготовленный ответ...')
#             # Если данные есть в кэше, возвращаем их
#             response = cached_data.decode('utf-8')
#         else:
#             print('Данных нет в кэше, отправляем запрос на сервак...')
#             # Если данных нет в кэше, делаем запрос к внешнему серверу
#             async with aiohttp.ClientSession() as session:
#                 url = 'https://hackaton.free.beeceptor.com/visa'
#                 async with session.put(url, json=request_data) as resp:
#                     if resp.status != 200:
#                         raise HTTPException(status_code=resp.status,
#                                             detail="Ошибка при получении данных с удаленного сервера")
#                     response = await resp.text()
#                     # Сохраняем полученные данные в кэше на случай повторного запроса
#                     await redis.set(cache_key, response)
#     finally:
#         # Закрываем соединение с Redis
#         redis.close()
#         # await redis.wait_closed()

#     return response


# # Маршрут для получения данных из кэша по ключу
# @app.get("/cache/{cache_key}")
# async def get_cache_data(cache_key: str):
#     # Подключение к Redis
#     redis = await get_redis()

#     try:
#         # Получаем данные из кэша по ключу
#         cached_data = await redis.get(cache_key)
#         if cached_data is None:
#             raise HTTPException(status_code=404, detail="Данные по ключу не найдены в кэше")

#         # Декодируем данные из байтов в строку и возвращаем
#         return {"cache_key": cache_key, "cached_data": cached_data.decode('utf-8')}

#     finally:
#         # Закрываем соединение с Redis
#         redis.close()


# # Маршрут для удаления данных из кэша по ключу
# @app.delete("/delete_cache/{cache_key}")
# async def delete_cache_data(cache_key: str):
#     # Подключение к Redis
#     redis = await get_redis()

#     try:
#         # Проверяем, есть ли данные в кэше по ключу
#         exists = await redis.exists(cache_key)
#         if not exists:
#             raise HTTPException(status_code=404, detail="Данные по ключу не найдены в кэше")

#         # Удаляем данные из кэша по ключу
#         await redis.delete(cache_key)
#         return {"message": f"Данные по ключу '{cache_key}' успешно удалены из кэша"}

#     finally:
#         # Закрываем соединение с Redis
#         redis.close()



