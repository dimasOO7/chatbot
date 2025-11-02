from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import uvicorn
from typing import Dict, List, Any # Импортируем типы для хранилища
from fastapi.staticfiles import StaticFiles   
# Загрузка переменных окружения
load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("Переменная окружения GEMINI_API_KEY не установлена.")

client = OpenAI(
    api_key= GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

# Инициализация приложения FastAPI
app = FastAPI(
    title="API чата OpenAI с использованием FastAPI",
    description="Простой сервис для пересылки сообщений чата модели GPT-3.5-Turbo.",
)
app.mount("/static", StaticFiles(directory="static"), name="static")
# --- Хранилище истории чатов (В ПАМЯТИ) ---
# ВНИМАНИЕ: Это хранилище находится в памяти.
# Вся история будет потеряна при перезапуске сервера.
# Формат: { "user_id_1": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}], ... }
chat_histories: Dict[str, List[Dict[str, Any]]] = {}

# --- Системный промпт ---
# Вынесем его в константу для удобства
SYSTEM_PROMPT = {"role": "system", "content": "Вы отзывчивый и пунктуальный помощник. Отвечаете профессионально и чётко. "}


# Модель Pydantic для валидации тела запроса
class MessageRequest(BaseModel):
    """Определяет ожидаемую структуру входящих данных JSON."""
    message: str
    user_id: str # <--- ДОБАВЛЕНО: Уникальный ID для каждого пользователя

# Модель для очистки истории
class UserIdRequest(BaseModel):
    user_id: str

# --- Маршруты ---

# 1. Корневой маршрут для отдачи HTML-интерфейса
@app.get("/", response_class=HTMLResponse)
async def index():
    """Обслуживает статический файл index.html."""
    return FileResponse("templates/index.html", media_type="text/html")

# 2. Конечная точка API для обработки сообщений пользователя
@app.post("/send_message")
async def send_message(req: MessageRequest):
    """
    Обрабатывает сообщение пользователя, загружает его историю,
    вызывает API OpenAI, сохраняет историю и возвращает ответ.
    """
    user_message_content = req.message
    user_id = req.user_id

    if not user_message_content:
        raise HTTPException(status_code=400, detail="Сообщение не может быть пустым.")
    if not user_id:
        # Клиент (JS) должен предоставить ID
        raise HTTPException(status_code=400, detail="user_id не может быть пустым.")

    # 1. Получение или инициализация истории пользователя
    if user_id not in chat_histories:
        chat_histories[user_id] = []
        print(f"Создана новая история для пользователя: {user_id}")
    
    user_history = chat_histories[user_id]
    
    # 2. Подготовка сообщения для API
    # Создаем словарь для нового сообщения пользователя
    new_user_message_dict = {"role": "user", "content": user_message_content}
    
    # Формируем полный список сообщений для отправки в API:
    # [Системный промпт] + [Вся предыдущая история] + [Новое сообщение пользователя]
    messages_to_send = [SYSTEM_PROMPT] + user_history + [new_user_message_dict]

    try:
        # 3. Вызов API завершения чата OpenAI
        completion = client.chat.completions.create(
            model="gemini-2.5-flash", 
            messages=messages_to_send # <--- ИЗМЕНЕНО: Отправляем всю историю
        )

        # 4. Извлечение ответа
        reply_content = completion.choices[0].message.content
        # Создаем словарь для ответа ассистента
        new_assistant_message_dict = {"role": "assistant", "content": reply_content}

        # 5. Обновление истории в нашем хранилище
        # Добавляем и сообщение пользователя, и ответ ассистента
        user_history.append(new_user_message_dict)
        user_history.append(new_assistant_message_dict)
        
        # 6. Возврат ответа
        return {"reply": reply_content}

    except Exception as e:
        print(f"Ошибка API OpenAI: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка связи с API: {str(e)}")

# 3. (Опционально) Конечная точка для очистки истории пользователя
@app.post("/clear_history")
async def clear_history(req: UserIdRequest):
    """Очищает историю для указанного user_id."""
    user_id = req.user_id
    if user_id in chat_histories:
        chat_histories[user_id] = []
        return {"status": "success", "message": f"История для {user_id} очищена."}
    else:
        return {"status": "not_found", "message": f"История для {user_id} не найдена."}


# Этот блок предназначен для выполнения в режиме локальной разработки
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)