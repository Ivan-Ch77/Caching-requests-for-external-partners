import hashlib
import json

from fastapi.responses import HTMLResponse
from fastapi import FastAPI, HTTPException
import aioredis
import aiohttp

app = FastAPI()


# Установка соединения с Redis
async def get_redis():
    return await aioredis.from_url('redis://localhost:6379')


# Обработчик запросов к прокси-серверу
@app.put("/proxy")
async def proxy(request_data: dict):
    # Подключение к Redis
    redis = await get_redis()

    # Создание уникального ключа кэша на основе хеша JSON-представления запроса
    request_json = json.dumps(request_data, sort_keys=True)
    cache_key = hashlib.sha256(request_json.encode()).hexdigest()
    print(cache_key)

    try:
        # Проверка, есть ли данные в кэше
        cached_data = await redis.get(cache_key)
        if cached_data:
            print('Данные есть в кэше, отправляем заготовленный ответ...')
            # Если данные есть в кэше, возвращаем их
            response = cached_data.decode('utf-8')
        else:
            print('Данных нет в кэше, отправляем запрос на сервак...')
            # Если данных нет в кэше, делаем запрос к внешнему серверу
            async with aiohttp.ClientSession() as session:
                url = 'https://hackaton.free.beeceptor.com/visa'
                async with session.put(url, json=request_data) as resp:
                    if resp.status != 200:
                        raise HTTPException(status_code=resp.status,
                                            detail="Ошибка при получении данных с удаленного сервера")
                    response = await resp.text()
                    # Сохраняем полученные данные в кэше на случай повторного запроса
                    await redis.set(cache_key, response)
    finally:
        # Закрываем соединение с Redis
        redis.close()
        # await redis.wait_closed()

    return response


# Маршрут для получения данных из кэша по ключу
@app.get("/cache/{cache_key}")
async def get_cache_data(cache_key: str):
    # Подключение к Redis
    redis = await get_redis()

    try:
        # Получаем данные из кэша по ключу
        cached_data = await redis.get(cache_key)
        if cached_data is None:
            raise HTTPException(status_code=404, detail="Данные по ключу не найдены в кэше")

        # Декодируем данные из байтов в строку и возвращаем
        return {"cache_key": cache_key, "cached_data": cached_data.decode('utf-8')}

    finally:
        # Закрываем соединение с Redis
        redis.close()


# Маршрут для удаления данных из кэша по ключу
@app.delete("/delete_cache/{cache_key}")
async def delete_cache_data(cache_key: str):
    # Подключение к Redis
    redis = await get_redis()

    try:
        # Проверяем, есть ли данные в кэше по ключу
        exists = await redis.exists(cache_key)
        if not exists:
            raise HTTPException(status_code=404, detail="Данные по ключу не найдены в кэше")

        # Удаляем данные из кэша по ключу
        await redis.delete(cache_key)
        return {"message": f"Данные по ключу '{cache_key}' успешно удалены из кэша"}

    finally:
        # Закрываем соединение с Redis
        redis.close()


# Обычный метод получения кэша в строке (возвращает строку). Можно заменить на словарь или еще что-то
# @app.get("/cached_data", summary="Get cached data keys", description="Retrieve keys of cached data")
# async def get_cached_data_keys():
#     # Подключение к Redis
#     redis = await get_redis()
#
#     try:
#         # Получаем все ключи из кэша
#         keys = await redis.keys('*')
#         cache_content = ""
#
#         # Получаем данные по каждому ключу и форматируем вывод
#         for key in keys:
#             cached_data = await redis.get(key)
#             cache_content += f"{key.decode('utf-8')}: {cached_data.decode('utf-8')}\n" if cached_data else f"{key.decode('utf-8')}: None\n"
#             print(cache_content)
#         return cache_content
#
#     finally:
#         # Закрываем соединение с Redis
#         redis.close()


# Метод красивого отображения списка кэшей в браузере
@app.get("/cached_data", response_class=HTMLResponse)
async def get_cache_content():
    # Подключение к Redis
        redis = await get_redis()

        try:
            # Получаем все ключи из кэша
            keys = await redis.keys('*')

            # Формирование HTML-строки с отступами и переносами строк
            cache_content_html = "<html><body>"
            for key in keys:
                cached_data = await redis.get(key)
                if cached_data:
                    cache_content_html += f"<p><b>{key.decode('utf-8')}:</b> {cached_data.decode('utf-8')}</p><br>"
                else:
                    cache_content_html += f"<p><b>{key.decode('utf-8')}:</b> None</p><br>"
            cache_content_html += "</body></html>"

            return HTMLResponse(content=cache_content_html)
        finally:
            # Закрываем соединение с Redis
            redis.close()
