import os
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

# def extract_subdomain(url: str) -> str:
#     parsed_url = urlparse(url)
#     path = parsed_url.path
#     # Разделяем путь на части и берем первую часть после основного домена
#     subdomain = path.split('/')[1] if path.startswith('/') else path.split('/')[0]
#     return subdomain


# Функция для загрузки данных из файла partners_info.json, если он существует
def load_partners_info():
    file_name = "partners_info.json"
    if os.path.exists(file_name):
        with open(file_name, "r") as file:
            return json.load(file)
    return {}


# Функция для сохранения данных в файл partners_info.json
def save_partners_info(data):
    file_name = "partners_info.json"
    with open(file_name, "w") as file:
        json.dump(data, file, indent=4)


def create_cache_key(method: str, url: str, body: dict, partner_name: str) -> str:
    def process_request(partner_name, data):
        if isinstance(data, dict):
            ignore_fields = []
            if partner_name in partners_info:
                ignore_fields = partners_info[partner_name].get("ignore_fields", [])

            return {
                k: process_request(partner_name, v) if k not in ignore_fields else None
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [
                process_request(partner_name, item)
                for item in data
            ]
        else:
            return data

    body_processed = process_request(partner_name, body)
    key_data = json.dumps({"method": method, "url": url, "body": body_processed, "partner_name": partner_name})
    # Хеширование ключа
    return key_data

# Урлы партнеров имени
# partners_info = {
#     "visa": {"url": "https://hackaton.free.beeceptor.com/visa", "ignore_fields": ["salt", "id"]},
#     "master": {"url": lambda: f"https://hackaton.free.beeceptor.com/master/{uuid.uuid4()}", "ignore_fields": ["salt"]}
# }
partners_info = dict(load_partners_info())


@app.api_route("/proxy/{partner_name}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, partner_name: str):
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
        if partner_name not in partners_info:
            raise HTTPException(status_code=404, detail=f"URL for subdomain '{partner_name}' not found")

        # Получение URL для перенаправления
        # url = urls[subdomain]() if callable(urls[subdomain]) else urls[subdomain]
        partner_data = partners_info[partner_name]
        url = partner_data["url"]() if callable(partner_data["url"]) else partner_data["url"]

        # Создание ключа кэша
        key = create_cache_key(method, url, body, partner_name)

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

#
# @app.post("/payment-callback/")
# async def payment_callback(callback_data: dict = Body(...)):
#     payment_id = callback_data.get("id")
#     payment_status = callback_data.get("status")
#
#     redis = await get_redis()
#     try:
#         # Получаем текущее значение по ключу
#         current_value = await redis.get(payment_id)
#         if current_value is None:
#             raise HTTPException(status_code=404, detail="Payment not found")
#
#         # Обновляем значение
#         current_data = json.loads(current_value)
#         current_data['status'] = payment_status  # Обновляем статус
#         await redis.set(payment_id, json.dumps(current_data))
#     finally:
#         await redis.close()
#
#     return {"status": "success", "message": f"Payment {payment_id} updated to {payment_status}"}


@app.get("/partners", response_class=HTMLResponse)
async def read_partners(request: Request):
    partners_data = load_partners_info()
    return templates.TemplateResponse("partners_page.html", {"request": request, "partners_data": partners_data})

@app.get("/get-partners")
async def get_partners():
    partners_data = load_partners_info()  # Загрузка информации о партнерах из файла
    return partners_data

@app.post("/add-partner")
async def add_partner(partner_data: dict = Body(...)):
    partner_name = partner_data.get("name")
    partner_url = partner_data.get("url")
    ignore_fields = partner_data.get("ignore_fields", [])

    if partner_name in partners_info:
        raise HTTPException(status_code=400, detail=f"Partner '{partner_name}' already exists")

    partners_info[partner_name] = {"url": partner_url, "ignore_fields": ignore_fields}

    # Сохранение обновленных данных в файл после добавления партнера
    save_partners_info(partners_info)

    return {"status": "success", "message": f"Partner '{partner_name}' added successfully"}


@app.api_route("/delete-partner/{partner_name}", methods=["GET", "DELETE"])
async def del_partner(partner_name: str):
    try:
        if partner_name in partners_info:
            del partners_info[partner_name]
            save_partners_info(partners_info)  # Сохранение обновленных данных в файл
            return {"status": "success", "message": f"Partner '{partner_name}' deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail=f"Partner '{partner_name}' not found")
    except Exception as e:
        logger.error(f"Error while deleting partner '{partner_name}': {e}")
        return {"error": f"Internal server error while deleting partner '{partner_name}'"}
