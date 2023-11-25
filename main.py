import uuid

import aioredis
from fastapi import FastAPI, Request, HTTPException
import httpx
import json
import logging
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from urllib.parse import urlparse
import xmltodict
import hashlib

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


def create_cache_key(method: str, url: str, body: dict, subdomain: str) -> str:
    # Игнорирование изменяемых полей ('salt')
    if body and 'salt' in body:
        body = {k: v for k, v in body.items() if k != 'salt'}

    key_data = json.dumps({"method": method, "url": url, "body": body, "subdomain": subdomain})
    # Хеширование ключа
    return hashlib.sha256(key_data.encode()).hexdigest()

# Урлы партнеров имени
urls = {
    "visa": "https://qiwi-hackathon.free.beeceptor.com/visa",
    "master": lambda: f"https://qiwi-hackathon.free.beeceptor.com/master/{uuid.uuid4()}"
}


@app.api_route("/proxy/{subdomain}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, subdomain: str):
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

        # Проверка наличия поддомена в словаре перенаправлений
        if subdomain not in urls:
            raise HTTPException(status_code=404, detail=f"URL для поддомена '{subdomain}' не найден")

        # Получение URL для перенаправления
        url = urls[subdomain]() if callable(urls[subdomain]) else urls[subdomain]

        # Создание ключа кэша
        key = create_cache_key(method, url, body, subdomain)

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

@app.api_route("/reset-cache/", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def reset_cache():
    redis = await get_redis()
    try:
        await redis.flushdb()
        return {"status": "Cache reset successfully"}
    except Exception as e:
        logger.error(f"Ошибка при сбросе кэша: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        await redis.close()


# @app.api_route("/reset-cache/{subdomain}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
# async def reset_cache_for_subdomain(subdomain: str):
#     redis = await get_redis()
#     try:
#         keys = await redis.keys("*")
#         for key in keys:
#             key_str = key.decode("utf-8")
#             if json.loads(key_str).get("subdomain") == subdomain:
#                 await redis.delete(key)
#         return {"status": f"Cache reset successfully for subdomain: {subdomain}"}
#     except Exception as e:
#         logger.error(f"Ошибка при сбросе кэша для поддомена {subdomain}: {e}")
#         raise HTTPException(status_code=500, detail="Internal Server Error")
#     finally:
#         await redis.close()