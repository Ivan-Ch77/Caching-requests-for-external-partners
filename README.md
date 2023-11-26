# MVP для кеширования повторяющихся запросов
Данное приложение позволяет кэшировать запросы и ответы от тестовых средств партнеров. Для снижения зависимости тестовой среды QIWI от тестовых сред партнеров.

## Развертывание приложения 

 #### Запуск Redis в Docker-контейнере:

- `docker run --name redis -p 6379:6379 -d redis`

#### Создание виртуального окружения
- `python3.10 -m venv venv` - нужна версия 3.10

- `source venv/bin/activate`

- `pip install -r "requirements.txt"`
#### Запуск FastAPI-сервера:

- `uvicorn main:app --reload` - По умолчинаю сервер разворачивается на http://localhost:8000/

## Фунционал приложения 
1. Добавление тестовой среды партнёра 
   
   Отправляем POST запрос на http://localhost:8000/add-partner с телом 
   
   ```
    {
        "name":"partner1",
        "url":"test.partner1.com",
        "ignore_fields": "id, description"
    }
   ```
   Поле `name` должно быть сторокой

   Поле `ignore_fields` не обязательное


2. Отправки запроса на тестовый сервер 
   
    Отправляем запрос на http://localhost:8000/proxy/{partner_name} 
    тело запроса может быть любым

    `partner_name` - partner1

3. Очищение кэша тестовой среды партнера
   
   Отправляем DELETE запрос на http://localhost:8000/get-partners/{partner_name} 
   
4. Удаление тестовой среды партнера 

   Отправляем DELETE запрос на http://localhost:8000/delete-partner/{partner_name} 

5. Очищение кэша всех партнеров
   
   Отправляем DELETE запрос на http://localhost:8000/reset-cache/

6. Получение информации о партнерах
   
   Отправляем GET запрос на http://localhost:8000/get-partners

**Дополнение** 

- Есть простой веб интерфейс для управления тестовыми средами партнеров для этого нужно перейти на страницу http://localhost:8000/partners 
- Также создан веб интерфейс для просмотра сохраненного кеша на странице http://localhost:8000/cached-requests/
