from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import uvicorn
from typing import Dict, List, Any, AsyncGenerator
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse
import aiosqlite
import json
import datetime
import asyncio
from asyncddgs import aDDGS
import aiohttp
from bs4 import BeautifulSoup


# --- Загрузка переменных окружения ---
load_dotenv()

# *** ИЗМЕНЕНИЕ: Используем только Cerebras ***
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")
if not CEREBRAS_API_KEY:
    raise ValueError("Переменная окружения CEREBRAS_API_KEY не установлена.")

# Клиент для Cerebras (фильтрация, принятие решений И генерация)
client = OpenAI(
    api_key=CEREBRAS_API_KEY,
    base_url="https://api.cerebras.ai/v1"
)

CLASSIFY_MODEL_ID = "llama-3.3-70b"  # Для классификации и решений (Llama)
GENERATE_MODEL_ID = "gpt-oss-120b"  # Для генерации ответов
#client = OpenAI(
#    api_key="ollama",
#    base_url="http://localhost:11434/v1"
#)

# *** ИЗМЕНЕНИЕ: Разные модели для разных задач ***
#CLASSIFY_MODEL_ID = "gemma3n"  # Для классификации и решений (Llama)
#GENERATE_MODEL_ID = "gemma3n"   # Для генерации ответов
# *** ИЗМЕНЕНИЕ КОНЕЦ ***

# закоментить то что выше и раскоментить это для использования джемени

#GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
#if not GEMINI_API_KEY:
#    raise ValueError("Переменная окружения GEMINI_API_KEY не установлена.")

#client = OpenAI(
#    api_key=GEMINI_API_KEY,
#    base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
#)

#CLASSIFY_MODEL_ID = "gemini-2.5-flash-дшеу"  # Для классификации и решений (Llama)
#GENERATE_MODEL_ID = "gemini-2.5-flash"   # Для генерации ответов

# --- Инициализация приложения ---
app = FastAPI(
    title="API чата Cerebras (Async SQLite + Поиск)",
    description="Асинхронный чат с историей, авто-классификацией и поиском DuckDuckGo.",
)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Настройка базы данных ---
DB_NAME = "database.db"

@app.on_event("startup")
async def startup_event():
    app.state.db = await aiosqlite.connect(DB_NAME)
    app.state.db.row_factory = aiosqlite.Row
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
    await app.state.db.close()
    print("🧹 Соединение с базой закрыто.")


# --- Системные промпты (Личности) ---

# *** ИЗМЕНЕНИЕ: Обновлены инструкции по использованию поиска (добавлены источники) ***
SEARCH_INSTRUCTION = (
    "\n\n**Важное правило:** Если в начале твоего контекста предоставлены 'Результаты Поиска', "
    "твой ответ должен быть основан **исключительно** на них. "
    "После ответа, **обязательно** приведи список использованных источников в формате (используя Markdown): \n"
    "**Источники:**\n"
    "1. [Название источника 1](URL)\n"
    "2. [Название источника 2](URL)\n"
    "3. [Название источника 3](URL)\n"
    "4. [Название источника 4](URL)\n"
    "5. [Название источника 5](URL)\n"
    "Не ссылайся на 'Результаты Поиска' в самом тексте ответа (не пиши 'согласно поиску...'). "
    "Если результатов поиска нет, отвечай, используя свои знания."
)

DEFAULT_PROMPT = {
    "role": "system",
    "content": "Вы — PNIbot, помощник по ведению малого бизнеса. Ваша задача — отвечать на вопросы, связанные с бизнесом, маркетингом, финансами и юриспруденцией. Будьте профессиональны и лаконичны." + SEARCH_INSTRUCTION
}

PERSONALITY_PROMPTS = {
    "default": DEFAULT_PROMPT,
    "marketing": {
        "role": "system",
        "content": "Вы — PNIbot, эксперт по маркетингу. Вы помогаете владельцам малого бизнеса с идеями для продвижения, анализом ЦА, SMM, SEO и контент-стратегиями. Отвечайте креативно, но по делу, предлагая конкретные шаги." + SEARCH_INSTRUCTION
    },
    "legal": {
        "role": "system",
        "content": "Вы — PNIbot, помощник по юридическим вопросам. Вы предоставляете ОБЩУЮ информацию по регистрации бизнеса, налогам, контрактам и интеллектуальной собственности. ВАЖНО: Всегда напоминайте пользователю, что вы не даете юридических консультаций (legal advice) и что для решения конкретной проблемы необходимо обратиться к квалифицированному юристу." + SEARCH_INSTRUCTION
    },
    "analyst": {
        "role": "system",
        "content": "Вы — PNIbot, бизнес-аналитик. Вы помогаете анализировать бизнес-идеи, оценивать рыночные ниши, составлять фин. модели и SWOT-анализ. Фокусируйтесь на данных, цифрах и структурированных ответах (например, списки, таблицы)." + SEARCH_INSTRUCTION
    }
}


# *** ИЗМЕНЕНИЕ НАЧАЛО: Новый единый промпт для классификации И принятия решения о поиске ***
ANALYSIS_PLAN_PROMPT_TEMPLATE = """
Ты — ИИ-ассистент, принимающий решения (Llama).
Твоя задача — проанализировать последний запрос пользователя и историю чата, чтобы составить план ответа.
Верни ТОЛЬКО JSON-объект и ничего больше.

1.  **Фильтрация (is_business):**
    -   Определи, относится ли запрос к ведению бизнеса (маркетинг, юриспруденция, финансы, управление, бухгалтерия, запуск компании и т.д.).
    -   Ключ: "is_business" (boolean: true или false).

2.  **Выбор личности (personality):**
    -   Если "is_business" - true, определи категорию: ["marketing", "legal", "analyst", "default"].
    -   "marketing": SMM, SEO, реклама, ЦА, контент-планы.
    -   "legal": Регистрация ООО/ИП, налоги, контракты, лицензии.
    -   "analyst": Бизнес-планы, SWOT-анализ, фин. модели, анализ рынка, KPI.
    -   "default": Общие вопросы о бизнесе.
    -   Если "is_business" - false, установи "personality" в "default".
    -   Ключ: "personality" (string).

3.  **Решение о поиске (needs_search):**
    -   Нужен ли поиск в интернете для ответа?
    -   Искать нужно (true): Запросы о текущих событиях (новости, погода, курсы валют СЕГОДНЯ), конкретных фактах, цифрах, статистике, законах, налогах, малоизвестных компаниях/продуктах.
    -   Искать НЕ нужно (false): Общие вопросы, на которые у LLM есть ответ (например, "что такое маркетинг"), вопросы о личном мнении, продолжение разговора, вопросы о предыдущих сообщениях в чате.
    -   Ключ: "needs_search" (boolean).

4.  **Поисковый запрос (search_query):**
    -   Если "needs_search" - true, сгенерируй краткий и точный поисковый запрос. Текущая дата: {date}
    -   Если "needs_search" - false, верни null.
    -   Ключ: "search_query" (string или null).

5.  **Количество результатов (num_results):**
    -   Если "needs_search" - true, реши, сколько страниц нужно для ответа (от 1 до 5).
    -   1: для простых фактов (погода, курс валюты).
    -   3: для большинства запросов (стандартное значение).
    -   5: для сложных тем, требующих всестороннего анализа.
    -   Если "needs_search" - false, верни 0.
    -   Ключ: "num_results" (integer: 0, 1, 3, 5).

История чата (последние 5 сообщений):
{history}

Запрос пользователя: "{query}"

Твой JSON-ответ:
"""
# *** ИЗМЕНЕНИЕ КОНЕЦ ***


# --- Модели ---
class MessageRequest(BaseModel):
    # *** ИЗМЕНЕНИЕ: Удалено поле 'personality' (остается удаленным) ***
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

# --- Логика фильтрации и стриминга ---

# *** ИЗМЕНЕНИЕ НАЧАЛО: Новая единая функция для анализа, фильтрации и принятия решений ***
async def _analyze_and_plan(user_query: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Использует Cerebras Llama для ОДНОВРЕМЕННОЙ
    1. Фильтрации (is_business)
    2. Выбора личности (personality)
    3. Решения о поиске (needs_search)
    4. Генерации поискового запроса (search_query)
    5. Выбора кол-ва результатов (num_results)
    """
    history_str = "\n".join([f"{m['role']}: {m['content'][:100]}..." for m in history])
    prompt = ANALYSIS_PLAN_PROMPT_TEMPLATE.format(
        date=datetime.datetime.now().strftime("%d.%m.%Y"),
        history=history_str,
        query=user_query
    )
    
    try:
        response = client.chat.completions.create(
            model=CLASSIFY_MODEL_ID, # Используем Llama
            messages=[
                {"role": "system", "content": "Ты — ИИ-анализатор. Твоя задача — проанализировать запрос и вернуть ТОЛЬКО JSON-объект с планом действий."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=400 # Увеличим, т.к. промпт и JSON стали сложнее
        )
        
        content = response.choices[0].message.content.strip() # type: ignore
        
        # *** ИЗМЕНЕНИЕ: Более надежная очистка JSON от Markdown-блоков ***
        if content.startswith("```"):
            try:
                # Находим часть после первой строки (``` или ```json)
                json_part = content.split("\n", 1)[1]
                # Убираем последнюю строку ```
                content = json_part.rsplit("\n```", 1)[0]
            except (IndexError, ValueError):
                print(f"Ошибка парсинга JSON-блока в _analyze_and_plan: {content}")
                pass
            
        print(f"Cerebras (Analysis/Plan) Response: {content}")
        data = json.loads(content)
        
        # Валидация и значения по умолчанию
        is_business = bool(data.get("is_business", False))
        personality = data.get("personality", "default")
        needs_search = bool(data.get("needs_search", False))
        search_query = data.get("search_query")
        num_results = int(data.get("num_results", 0))

        # Логическая коррекция: если не бизнес, то не ищем и личность = default
        if not is_business:
            return {
                "is_business": False,
                "personality": "default",
                "needs_search": False,
                "search_query": None,
                "num_results": 0
            }
        
        # Логическая коррекция: если ищем, но нет запроса, отменяем поиск
        if needs_search and not search_query:
            needs_search = False
            num_results = 0

        # Логическая коррекция: если не ищем, сбрасываем запрос и кол-во
        if not needs_search:
            search_query = None
            num_results = 0

        return {
            "is_business": is_business,
            "personality": personality if personality in PERSONALITY_PROMPTS else "default",
            "needs_search": needs_search,
            "search_query": search_query,
            "num_results": num_results
        }

    except Exception as e:
        print(f"Ошибка классификации/планирования (Cerebras): {e}")
        # Безопасный режим: считаем, что это не бизнес-вопрос, если модель сломалась
        return {
            "is_business": False,
            "personality": "default",
            "needs_search": False,
            "search_query": None,
            "num_results": 0
        }
# *** ИЗМЕНЕНИЕ КОНЕЦ ***


# *** ИЗМЕНЕНИЕ НАЧАЛО: Функции поиска (остаются, но _search_duckduckgo обновлен) ***
async def _fetch_and_parse(session: aiohttp.ClientSession, url: str) -> str:
    """
    Асинхронно загружает URL, парсит HTML и возвращает очищенный текст.
    """
    # Максимальное кол-во символов с одной страницы для передачи в LLM
    MAX_TEXT_LENGTH = 10000 
    
    try:
        # Устанавливаем User-Agent, чтобы имитировать браузер, и таймаут
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        
        async with session.get(url, timeout=5, headers=headers) as response:
            if response.status != 200:
                return f"Не удалось загрузить (статус: {response.status})"
            
            # Проверяем, что это HTML, а не PDF или изображение
            if 'text/html' not in response.headers.get('Content-Type', ''):
                 return "Контент не является HTML-страницей."
                 
            html = await response.text()
            
            # Используем BeautifulSoup для парсинга
            soup = BeautifulSoup(html, 'html.parser')
            
            # Удаляем все теги <script> и <style>, так как они не нужны LLM
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
                
            # Получаем чистый текст
            text = soup.get_text()
            
            # Очищаем текст от лишних пробелов и переносов строк
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            if not text:
                return "Не удалось извлечь текст из HTML."
            
            # Укорачиваем текст до MAX_TEXT_LENGTH
            return text[:MAX_TEXT_LENGTH] + "..." if len(text) > MAX_TEXT_LENGTH else text

    except asyncio.TimeoutError:
        return "Не удалось загрузить (тайм-аут)."
    except Exception as e:
        # Ловим общие ошибки (например, SSL, DNS)
        print(f"Ошибка при загрузке {url}: {e}")
        return f"Ошибка при загрузке контента: {str(e)}"

# *** ИЗМЕНЕНИЕ: _search_duckduckgo теперь принимает max_results ***
async def _search_duckduckgo(query: str, max_results: int) -> str:
    """
    Выполняет асинхронный поиск,
    **загружает контент страниц** и форматирует результаты.
    """
    
    # Ограничиваем кол-во результатов (безопасность)
    if not 1 <= max_results <= 5:
        print(f"Некорректное кол-во результатов ({max_results}), установлено 3.")
        max_results = 3
        
    print(f"Выполнение поиска ({max_results} стр.): {query}")
    results_data = []
    
    # --- Шаг 1: Получаем URL-адреса из DuckDuckGo ---
    try:
        async with aDDGS() as ddgs:
            # Ищем N лучших результатов
            results = await ddgs.text(query, max_results=max_results) # <-- Используем параметр
            
            if not results:
                return "Результаты Поиска: Не найдено."
            
            # Сохраняем исходные данные. r['body'] - это сниппет.
            # Мы будем использовать его как запасной вариант, если загрузка страницы не удастся.
            results_data = results 
            
    except Exception as e:
        print(f"Ошибка поиска DuckDuckGo: {e}")
        return "Результаты Поиска: Ошибка при выполнении."

    # --- Шаг 2: Асинхронно загружаем и парсим контент ---
    formatted_results = ["Результаты Поиска (используй их для ответа, в конце ответа приведи источники):"]
    
    async with aiohttp.ClientSession() as session:
        # Создаем список задач для параллельной загрузки
        tasks = []
        for r in results_data:
            tasks.append(_fetch_and_parse(session, r['href']))
        
        # Выполняем все запросы параллельно
        fetched_contents = await asyncio.gather(*tasks)

        # --- Шаг 3: Форматируем результаты для LLM ---
        for i, (r, fetched_text) in enumerate(zip(results_data, fetched_contents)):
            
            # Определяем, какой текст использовать:
            # Если загрузка не удалась (содержит "Не удалось", "Ошибка" и т.д.),
            # используем ОРИГИНАЛЬНЫЙ сниппет (r['body']) из поиска.
            # В противном случае используем новый, загруженный текст.
            
            final_content = fetched_text
            if "Не удалось" in fetched_text or "Ошибка" in fetched_text or "не является HTML" in fetched_text or "Не удалось извлечь" in fetched_text:
                 final_content = r['body'] # Fallback на оригинальный сниппет
            
            formatted_results.append(
                f"Источник {i+1}: [URL: {r['href']}] [ТЕКСТ: {final_content}]"
            )
    
    return "\n".join(formatted_results)
# *** ИЗМЕНЕНИЕ КОНЕЦ ***


async def _stream_canned_response(message: str) -> AsyncGenerator[str, None]:
    """
    Стримит заранее заданный ответ (например, об ошибке или фильтре).
    """
    yield message
    await asyncio.sleep(0)


# *** ИЗМЕНЕНИЕ: Функция переименована и переведена на Cerebras (без изменений в этой функции) ***
async def _stream_cerebras_response(
    system_prompt: Dict[str, str],
    current_messages: List[Dict[str, str]],
    search_context: str | None, # <-- Новое: принимает результаты поиска
    chat_id: str,
    user_id: str,
    chat_name: str,
    is_new_chat: bool
) -> AsyncGenerator[str, None]:
    """
    Генератор, который стримит ответ от Cerebras и
    по завершению сохраняет полную историю в БД.
    """
    full_reply_content = []
    
    # *** ИЗМЕНЕНИЕ: Формируем финальный список сообщений ***
    final_messages = [system_prompt]
    
    if search_context:
        # Добавляем результаты поиска как системное сообщение
        final_messages.append({"role": "system", "content": search_context})
    
    # Добавляем историю чата
    final_messages.extend(current_messages)
    
    try:
        # Запускаем стриминг от Cerebras
        stream = client.chat.completions.create(
            model=GENERATE_MODEL_ID, # Используем gpt-oss120b
            messages=final_messages, # type: ignore
            stream=True
        )

        # Отправляем чанки клиенту
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                full_reply_content.append(content)
                yield content

    except Exception as e:
        print(f"Ошибка API Cerebras (стрим): {e}")
        yield f"Ошибка API: {str(e)}"
    
    finally:
        # По завершению стрима, сохраняем ПОЛНЫЙ ответ в БД
        full_message = "".join(full_reply_content)
        
        if full_message:
            # Добавляем в историю только 'user' и 'assistant'
            # (system_prompt и search_context не сохраняем в БД)
            current_messages.append({"role": "assistant", "content": full_message})
            
            await _update_chat_in_db(
                chat_id=chat_id,
                user_id=user_id,
                chat_name=chat_name,
                messages=current_messages, # Сохраняем историю без промптов
                is_new_chat=is_new_chat
            )


# --- Маршруты ---
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("templates/index.html", media_type="text/html")


@app.post("/send_message_stream")
async def send_message_stream(req: MessageRequest): # <-- Модель обновлена
    """
    Обрабатывает сообщение, выполняет единый анализ (фильтр + поиск),
    выполняет поиск (если нужно) и стримит ответ.
    """
    if not req.message or not req.user_id or not req.chat_id:
        raise HTTPException(status_code=400, detail="Все поля обязательны.")

    # 1. Получение данных чата (нужно для истории в _analyze_and_plan)
    chat_data = await _get_chat_from_db(req.chat_id)
    is_new_chat = chat_data is None

    if is_new_chat:
        chat_name = req.message[:30]
        current_messages = [] # История (без системных промптов)
    else:
        chat_name = chat_data["chat_name"]
        current_messages = chat_data["messages"]
        
    # 2. *** НОВЫЙ ЕДИНЫЙ ШАГ: Анализ, Фильтрация, Решение о поиске ***
    # Используем Llama для принятия всех решений в одном вызове
    analysis = await _analyze_and_plan(req.message, current_messages[-5:]) # Последние 5 сообщ. для контекста
    
    is_relevant = analysis.get("is_business", False)
    
    # 3. Если фильтр не пройден
    if not is_relevant:
        canned_response = "К сожалению, я могу отвечать только на вопросы, связанные с ведением бизнеса, маркетингом, финансами или юриспруденцией."
        return StreamingResponse(
            _stream_canned_response(canned_response),
            media_type="text/event-stream"
        )

    # 4. Определение "личности" (автоматически из analysis)
    final_personality_key = analysis.get("personality", "default")
    system_prompt = PERSONALITY_PROMPTS.get(final_personality_key, DEFAULT_PROMPT)

    # 5. Выполнение поиска (если анализ решил, что это нужно)
    search_context = None
    if analysis.get("needs_search") and analysis.get("search_query") and analysis.get("num_results") > 0:
        search_context = await _search_duckduckgo(
            analysis.get("search_query"),
            analysis.get("num_results")
        )

    # 6. Добавляем текущее сообщение пользователя в историю для генерации
    current_messages.append({"role": "user", "content": req.message})

    # 7. Возвращаем StreamingResponse, который вызывает генератор Cerebras
    return StreamingResponse(
        _stream_cerebras_response(
            system_prompt,
            current_messages,
            search_context,
            req.chat_id,
            req.user_id,
            chat_name,
            is_new_chat
        ),
        media_type="text/event-stream"
    )


@app.post("/get_chats")
async def get_chats(req: UserIdRequest):
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
    chat_data = await _get_chat_from_db(req.chat_id)
    if not chat_data or chat_data["user_id"] != req.user_id:
        raise HTTPException(status_code=4404, detail="Чат не найден или не принадлежит пользователю.")
    return {
        "chat_id": chat_data["chat_id"],
        "name": chat_data["chat_name"],
        "messages": chat_data["messages"]
    }

@app.post("/delete_chat")
async def delete_chat(req: ChatHistoryRequest):
    if not req.user_id or not req.chat_id:
        raise HTTPException(status_code=400, detail="user_id и chat_id обязательны.")

    db = get_db()
    
    async with db.execute(
        "SELECT user_id FROM chats WHERE chat_id = ?", (req.chat_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row or row["user_id"] != req.user_id:
        raise HTTPException(status_code=404, detail="Чат не найден или не принадлежит пользователю.")
    
    await db.execute("DELETE FROM chats WHERE chat_id = ?", (req.chat_id,))
    await db.commit()
    
    return {"status": "ok", "message": "Чат удален"}

# --- Точка входа ---
if __name__ == "__main__":
    # Напоминание: для работы поиска нужна библиотека
    # pip install duckduckgo-search asyncddgs
    uvicorn.run(app, host="0.0.0.0", port=8000)