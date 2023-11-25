import uuid
import aioredis
from fastapi import FastAPI, Request, HTTPException, Body
import httpx
import json
import logging
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
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


def create_cache_key(method: str, url: str, body: dict, subdomain: str) -> str:
    ignore_fields = partners_info[subdomain].get("ignore_fields", [])
    if body:
        body = {k: v for k, v in body.items() if k not in ignore_fields}
    key_data = json.dumps({"method": method, "url": url, "body": body, "subdomain": subdomain})
    return key_data

# Урлы партнеров имени
partners_info = {
    "visa": {"url": "https://qiwi-hackathon.free.beeceptor.com/visa", "ignore_fields": ["salt", "id"]},
    "master": {"url": lambda: f"https://qiwi-hackathon.free.beeceptor.com/master/{uuid.uuid4()}", "ignore_fields": ["salt"]}
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
        if subdomain not in partners_info:
            raise HTTPException(status_code=404, detail=f"URL for subdomain '{subdomain}' not found")

        # Получение URL для перенаправления
        partner_data = partners_info[subdomain]
        url = partner_data["url"]() if callable(partner_data["url"]) else partner_data["url"]

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


@app.api_route("/clear-cache/{domain}", methods=["GET", "DELETE"])
async def clear_partner_cache(domain: str):
    redis = await get_redis()
    try:
        keys = await redis.keys("*")
        for key in keys:
            key = key.decode('utf-8')
            key_json = json.loads(key)
            if domain == key_json['subdomain']:
                await redis.delete(key)
        return {"message": f"Cache for partner domain '{domain}' cleared successfully"}
    except Exception as e:
        logger.error(f"Error while clearing cache for partner domain '{domain}': {e}")
        return {"error": f"Internal server error while clearing cache for partner domain '{domain}'"}
    finally:
        await redis.close()


@app.post("/payment-callback/")
async def payment_callback(callback_data: dict = Body(...)):
    payment_id = callback_data.get("id")
    payment_status = callback_data.get("status")

    redis = await get_redis()
    try:
        # Получаем текущее значение по ключу
        current_value = await redis.get(payment_id)
        if current_value is None:
            raise HTTPException(status_code=404, detail="Payment not found")

        # Обновляем значение
        current_data = json.loads(current_value)
        current_data['status'] = payment_status  # Обновляем статус
        await redis.set(payment_id, json.dumps(current_data))
    finally:
        await redis.close()

    return {"status": "success", "message": f"Payment {payment_id} updated to {payment_status}"}

@app.post("/add-partner/")
async def add_partner(partner_data: dict = Body(...)):
    partner_name = partner_data.get("name")
    partner_url = partner_data.get("url")
    ignore_fields = partner_data.get("ignore_fields", [])

    if partner_name in partners_info:
        raise HTTPException(status_code=400, detail=f"Partner '{partner_name}' already exists")

    partners_info[partner_name] = {"url": partner_url, "ignore_fields": ignore_fields}

    return {"status": "success", "message": f"Partner '{partner_name}' added successfully"}
