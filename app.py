from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import uvicorn
from typing import Dict, List, Any, AsyncGenerator
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse  # <-- Импорт для стриминга
import aiosqlite
import json
import datetime


# --- Загрузка переменных окружения ---
load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("Переменная окружения GEMINI_API_KEY не установлена.")

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
)

# --- Инициализация приложения ---
app = FastAPI(
    title="API чата Gemini (Async SQLite + Pool)",
    description="Асинхронный чат с историей сообщений и оптимизированным подключением к SQLite.",
)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Настройка базы данных ---
DB_NAME = "database.db"

# Храним глобальное соединение в app.state
@app.on_event("startup")
async def startup_event():
    app.state.db = await aiosqlite.connect(DB_NAME)
    app.state.db.row_factory = aiosqlite.Row

    # Инициализация таблицы
    await app.state.db.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            chat_id TEXT UNIQUE NOT NULL,
            chat_name TEXT NOT NULL,
            messages TEXT,
            updated_at TEXT
        )
    ''')
    await app.state.db.commit()
    print("✅ База данных инициализирована.")

@app.on_event("shutdown")
async def shutdown_event():
    """Закрытие соединения при остановке сервера."""
    await app.state.db.close()
    print("🧹 Соединение с базой закрыто.")

# --- Системный промпт ---
SYSTEM_PROMPT = {
    "role": "system",
    "content": "Вы отзывчивый и пунктуальный помощник. Отвечаете профессионально и чётко."
}

# --- Модели ---
class MessageRequest(BaseModel):
    message: str
    user_id: str
    chat_id: str

class ChatHistoryRequest(BaseModel):
    user_id: str
    chat_id: str

class UserIdRequest(BaseModel):
    user_id: str

# --- Утилита для доступа к БД ---
def get_db():
    """Возвращает текущее подключение к БД (из пула)."""
    return app.state.db

# --- Функции работы с БД ---
async def _get_chat_from_db(chat_id: str) -> Dict[str, Any] | None:
    db = get_db()
    async with db.execute(
        "SELECT user_id, chat_name, messages FROM chats WHERE chat_id = ?", (chat_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if row:
        messages = json.loads(row["messages"]) if row["messages"] else []
        return {
            "chat_id": chat_id,
            "user_id": row["user_id"],
            "chat_name": row["chat_name"],
            "messages": messages,
        }
    return None


async def _update_chat_in_db(chat_id: str, user_id: str, chat_name: str,
                             messages: List[Dict[str, str]], is_new_chat: bool = False):
    db = get_db()
    messages_json = json.dumps(messages)
    updated_at = datetime.datetime.now().isoformat()

    if is_new_chat:
        await db.execute("""
            INSERT INTO chats (user_id, chat_id, chat_name, messages, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, chat_id, chat_name, messages_json, updated_at))
    else:
        await db.execute("""
            UPDATE chats SET chat_name = ?, messages = ?, updated_at = ?
            WHERE chat_id = ?
        """, (chat_name, messages_json, updated_at, chat_id))

    await db.commit()

# --- Логика стриминга ---

async def _stream_gemini_response(
    current_messages: List[Dict[str, str]],
    chat_id: str,
    user_id: str,
    chat_name: str,
    is_new_chat: bool
) -> AsyncGenerator[str, None]:
    """
    Генератор, который стримит ответ от Gemini и
    по завершению сохраняет полную историю в БД.
    """
    full_reply_content = []
    
    try:
        # Запускаем стриминг
        stream = client.chat.completions.create(
            model="gemini-2.5-flash-lite", 
            messages=[SYSTEM_PROMPT] + current_messages,
            stream=True
        )

        # Отправляем чанки клиенту
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                full_reply_content.append(content)
                yield content

    except Exception as e:
        print(f"Ошибка API Gemini (стрим): {e}")
        yield f"Ошибка API: {str(e)}"
    
    finally:
        # По завершению стрима, сохраняем ПОЛНЫЙ ответ в БД
        full_message = "".join(full_reply_content)
        
        # Сохраняем, только если был получен ответ
        if full_message:
            current_messages.append({"role": "assistant", "content": full_message})
            
            # Если это был новый чат, а имя было слишком длинным,
            # (что маловероятно, т.к. мы уже его обрезали),
            # здесь можно его еще раз установить.
            
            await _update_chat_in_db(
                chat_id=chat_id,
                user_id=user_id,
                chat_name=chat_name,
                messages=current_messages,
                is_new_chat=is_new_chat
            )


# --- Маршруты ---
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("templates/index.html", media_type="text/html")


@app.post("/send_message_stream") # <-- Новый эндпоинт для стрима
async def send_message_stream(req: MessageRequest):
    """Обрабатывает сообщение, вызывает Gemini API и стримит ответ."""
    if not req.message or not req.user_id or not req.chat_id:
        raise HTTPException(status_code=400, detail="Все поля обязательны.")

    chat_data = await _get_chat_from_db(req.chat_id)
    is_new_chat = chat_data is None

    if is_new_chat:
        chat_name = req.message[:30] # Имя чата = первые 30 симв.
        current_messages = []
    else:
        chat_name = chat_data["chat_name"]
        current_messages = chat_data["messages"]

    current_messages.append({"role": "user", "content": req.message})

    # Возвращаем StreamingResponse, который вызывает наш генератор
    return StreamingResponse(
        _stream_gemini_response(
            current_messages, req.chat_id, req.user_id, chat_name, is_new_chat
        ),
        media_type="text/event-stream"
    )


@app.post("/get_chats")
async def get_chats(req: UserIdRequest):
    """Возвращает список чатов пользователя."""
    if not req.user_id:
        raise HTTPException(status_code=400, detail="user_id не может быть пустым.")

    db = get_db()
    chats_list = []
    async with db.execute("""
        SELECT chat_id, chat_name, messages, updated_at
        FROM chats WHERE user_id = ?
        ORDER BY updated_at DESC
    """, (req.user_id,)) as cursor:
        async for row in cursor:
            messages = json.loads(row["messages"]) if row["messages"] else []
            last_msg = messages[-1]["content"] if messages else None
            chats_list.append({
                "id": row["chat_id"],
                "name": row["chat_name"],
                "preview": last_msg,
                "updatedAt": row["updated_at"]
            })
    return {"chats": chats_list}


@app.post("/get_chat_history")
async def get_chat_history(req: ChatHistoryRequest):
    """Возвращает историю конкретного чата."""
    chat_data = await _get_chat_from_db(req.chat_id)
    if not chat_data or chat_data["user_id"] != req.user_id:
        raise HTTPException(status_code=404, detail="Чат не найден или не принадлежит пользователю.")
    return {
        "chat_id": chat_data["chat_id"],
        "name": chat_data["chat_name"],
        "messages": chat_data["messages"]
    }

@app.post("/delete_chat")
async def delete_chat(req: ChatHistoryRequest):
    """Удаляет чат из базы данных."""
    if not req.user_id or not req.chat_id:
        raise HTTPException(status_code=400, detail="user_id и chat_id обязательны.")

    db = get_db()
    
    # Сначала проверяем, что чат принадлежит этому пользователю
    async with db.execute(
        "SELECT user_id FROM chats WHERE chat_id = ?", (req.chat_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row or row["user_id"] != req.user_id:
        raise HTTPException(status_code=404, detail="Чат не найден или не принадлежит пользователю.")
    
    # Удаляем чат
    await db.execute("DELETE FROM chats WHERE chat_id = ?", (req.chat_id,))
    await db.commit()
    
    return {"status": "ok", "message": "Чат удален"}

# --- Точка входа ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)