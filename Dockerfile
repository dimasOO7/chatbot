# Используем официальный образ Python
FROM python:3.14-slim

# Установка рабочей директории
WORKDIR /app

# Устанавливаем системные зависимости, необходимые для некоторых библиотек (например, pypdf)
RUN apt-get update && apt-get install -y \
    gcc \
    # Добавьте другие, если требуются (например, libpq-dev для PostgreSQL)
    && rm -rf /var/lib/apt/lists/*

# Копируем только файл зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальное содержимое проекта
COPY . .

# Приложение слушает порт 8000 (внутренний порт Docker)
EXPOSE 8000

# Запускаем Uvicorn (gunicorn + uvicorn workers - для продакшена)
# Здесь оставляем uvicorn.run из app.py, как в оригинале.
# Для prod-ready развертывания лучше использовать Gunicorn + Uvicorn worker.
# Но для простоты:
CMD ["python", "app.py"]