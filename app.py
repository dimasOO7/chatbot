# *** ИЗМЕНЕНИЕ: Новые импорты для FormData и чтения файлов ***
from fastapi import FastAPI, HTTPException, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
import os
import uvicorn
# *** ИЗМЕНЕНИЕ: Добавлен 'Optional' ***
from typing import Dict, List, Any, AsyncGenerator, Optional
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse
import aiosqlite
import json
import datetime
import asyncio
from asyncddgs import aDDGS
import aiohttp
from bs4 import BeautifulSoup
import re  # <-- Impor для ekspresi reguler

# *** ИЗМЕНЕНИЕ: Новые импорты для чтения файлов ***
import io
import pandas as pd
import docx
from pypdf import PdfReader
from fastapi import Form, UploadFile, File
from starlette.datastructures import UploadFile as StarletteUploadFile

# --- Regex для deteksi URL ---
# Regex umum для menemukan URL
URL_REGEX = re.compile(r'https://[\w\.-]+[/\w\.-]*')
# Regex для mengekstrak ID Google Doc
DOC_RE = re.compile(r"/document/d/([\w-]+)")
# Regex для mengekstrak ID Google Sheet
SHEET_RE = re.compile(r"/spreadsheets/d/([\w-]+)")


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

#CLASSIFY_MODEL_ID = "gemini-2.5-flash-lite"  # Для классификации и решений (Llama)
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
    "\n\n**Важное правило:** Если в начале твоего контекста предоставлены 'Результаты Поиска' или 'Контекст, извлеченный из URL' "
    "или 'Контекст, извлеченный из прикрепленного файла', " # <-- ИЗМЕНЕНИЕ: Добавлен файл
    "твой ответ должен быть основан **исключительно** на них. "
    "Если есть 'Результаты Поиска', **обязательно** приведи список использованных источников в формате (используя Markdown): \n"
    "**Источники:**\n"
    "1. [Название источника 1](URL)\n"
    "2. [Название источника 2](URL)\n"
    "3. [Название источника 3](URL)\n"
    "4. [Название источника 4](URL)\n"
    "5. [Название источника 5](URL)\n"
    "Не ссылайся на 'Результаты Поиска' в самом тексте ответа (не пиши 'согласно поиску...'). "
    "Если результатов поиска или URL/файла нет, отвечай, используя свои знания."
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
    -   Искать НЕ нужно (false): Общие вопросы, на которые у LLM есть ответ (например, "что такое маркетинг"), вопросы о личном мнении, продолжение разговора, вопросы о предыдущих сообщениях в чате, **если в запросе пользователя уже есть ссылки (URL) или прикреплен файл (сообщение содержит '(Прикреплен файл: ...)')**.
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
# *** ИЗМЕНЕНИЕ: Модель MessageRequest больше не используется для /send_message_stream, ***
# *** так как мы перешли на FormData. Оставляем для справки или удаляем. ***
# class MessageRequest(BaseModel):
#     message: str 
#     user_id: str
#     chat_id: str
#     file_content: str | None = None 
#     file_name: str | None = None   

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


# *** ИЗМЕНЕНИЕ НАЧАЛО: Функции поиска и загрузки URL ***

async def _fetch_google_doc_content(session: aiohttp.ClientSession, url: str) -> str | None:
    """
    Пытается загрузить контент из Google Doc или Sheet, используя /export.
    Возвращает текст (txt/csv) или None, если URL не соответствует.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
    
    doc_match = DOC_RE.search(url)
    sheet_match = SHEET_RE.search(url)
    
    export_url = None
    
    if doc_match:
        doc_id = doc_match.group(1)
        export_url = f"[https://docs.google.com/document/d/](https://docs.google.com/document/d/){doc_id}/export?format=txt"
    elif sheet_match:
        sheet_id = sheet_match.group(1)
        export_url = f"[https://docs.google.com/spreadsheets/d/](https://docs.google.com/spreadsheets/d/){sheet_id}/export?format=csv"

    if not export_url:
        return None # Это не Google Doc/Sheet, который мы можем обработать

    MAX_DOC_LENGTH = 3000 # Ограничение на размер контента из одного документа
    
    try:
        print(f"Загрузка Google Doc/Sheet: {export_url}")
        async with session.get(export_url, timeout=7, headers=headers) as response:
            if response.status != 200:
                return f"[Не удалось загрузить URL: {url} (статус: {response.status})]"
            
            # Читаем как байты, чтобы избежать проблем с кодировкой, затем декодируем
            content_bytes = await response.read()
            text_content = ""
            
            # Пытаемся декодировать
            try:
                text_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_content = content_bytes.decode('windows-1251') # Запасной вариант
                except Exception as e:
                    return f"[Не удалось декодировать контент из {url}: {e}]"
            
            return text_content[:MAX_DOC_LENGTH] + "..." if len(text_content) > MAX_DOC_LENGTH else text_content

    except asyncio.TimeoutError:
        return f"[Не удалось загрузить URL: {url} (тайм-аут)]"
    except Exception as e:
        print(f"Ошибка при загрузке Google Doc {url}: {e}")
        return f"[Ошибка при загрузке URL {url}: {str(e)}]"


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
    # current_messages УЖЕ содержит:
    # 1. Историю до этого
    # 2. (Если было) Скрытое сообщение с контентом URL или ФАЙЛА
    # 3. Текущее видимое сообщение пользователя
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
                messages=current_messages, # Сохраняем историю (включая скрытое сообщение)
                is_new_chat=is_new_chat
            )


# *** ИЗМЕНЕНИЕ: Новая вспомогательная функция для чтения файлов ***
MAX_FILE_CONTEXT_LENGTH = 15000
async def _read_uploaded_file(file: UploadFile) -> str:
    """
    Асинхронно читает UploadFile и возвращает его текстовое содержимое.
    Поддерживает .txt, .csv, .xlsx, .docx.
    """
    filename = file.filename or ""
    
    # Определяем расширение. Если его нет, считаем 'txt'.
    if '.' not in filename:
        extension = 'txt'
    else:
        # Берем последнее расширение
        extension = filename.rsplit('.', 1)[-1].lower()

    print(f"Парсинг файла: {filename} (тип: {extension})")
    
    content_bytes = await file.read()
    text_content = None

    try:
        if extension == 'xlsx':
            bytes_io = io.BytesIO(content_bytes)
            # Читаем все листы
            xls = pd.ExcelFile(bytes_io, engine='openpyxl')
            all_sheets = []
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                # Конвертируем DataFrame в CSV-подобный текст
                all_sheets.append(f"--- Лист: {sheet_name} ---\n{df.to_csv(index=False)}")
            text_content = "\n\n".join(all_sheets)
        
        elif extension == 'docx':
            bytes_io = io.BytesIO(content_bytes)
            doc = docx.Document(bytes_io)
            all_paragraphs = [p.text for p in doc.paragraphs]
            text_content = "\n".join(all_paragraphs)

        elif extension == 'pdf':
            bytes_io = io.BytesIO(content_bytes)
            reader = PdfReader(bytes_io)
            all_pages = [page.extract_text() for page in reader.pages if page.extract_text()]
            text_content = "\n\n--- Новая страница ---\n\n".join(all_pages)
        
        elif extension in ('txt', 'csv', 'html') or '.' not in filename:
            # Для текстовых форматов (включая CSV, HTML и файлы без расширения)
            try:
                text_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # Запасной вариант
                text_content = content_bytes.decode('windows-1251')
            
            if extension == 'html':
                # Очищаем HTML от тегов
                soup = BeautifulSoup(text_content, 'html.parser')
                text_content = soup.get_text(separator="\n", strip=True)
            
            # Для .csv и .txt просто возвращаем текст как есть
        
        else:
            # Если расширение неизвестно, но это не бинарный формат,
            # пытаемся прочитать как текст в последнюю очередь
            try:
                text_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_content = content_bytes.decode('windows-1251')
                except UnicodeDecodeError:
                    print(f"Файл {filename} имеет неизвестное расширение и не является текстом.")
                    return None # Не удалось распознать

    except Exception as e:
        print(f"Ошибка парсинга файла {filename} (ext: {extension}): {e}")
        # Возвращаем None, чтобы обработчик мог сообщить об ошибке
        return None

    if text_content is None:
        return None
        
    # Обрезаем контент, если он слишком длинный
    if len(text_content) > MAX_FILE_CONTEXT_LENGTH:
        text_content = text_content[:MAX_FILE_CONTEXT_LENGTH] + \
                       f"\n... [СОДЕРЖИМОЕ ФАЙЛА '{filename}' ОБРЕЗАНО] ..."
    
    return text_content


# --- Маршруты ---
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("templates/index.html", media_type="text/html")


# *** ИЗМЕНЕНИЕ: Сигнатура и логика /send_message_stream обновлены для FormData ***
@app.post("/send_message_stream")
async def send_message_stream(
    message: str = Form(""),
    user_id: str = Form(...),
    chat_id: str = Form(...),
    file: Optional[UploadFile] = File(None)
):
    """
    Обрабатывает сообщение (из FormData), выполняет единый анализ (фильтр + поиск),
    выполняет поиск (если нужно) и стримит ответ.
    """
    
    # 1. *** ИЗМЕНЕНИЕ: Читаем файл и получаем контент ***
    file_content: str | None = None
    file_name: str | None = None

    if file:
        file_name = file.filename
        file_content = await _read_uploaded_file(file) # Используем новую функцию
    
    # Проверяем, что есть хотя бы сообщение или *успешно* прочитанный файл
    if not message and not file_content:
        raise HTTPException(status_code=400, detail="Сообщение или файл должны присутствовать (или файл не удалось прочитать).")
        
    if not user_id or not chat_id:
        raise HTTPException(status_code=400, detail="user_id и chat_id обязательны.")

    # 2. Получение данных чата
    chat_data = await _get_chat_from_db(chat_id)
    is_new_chat = chat_data is None

    if is_new_chat:
        current_messages = [] # История (без системных промптов)
    else:
        chat_name = chat_data["chat_name"]
        current_messages = chat_data["messages"]
        
    # *** ИЗМЕНЕНИЕ: Логика контекста (Приоритет: Файл -> GDoc -> Поиск) ***

    # 3. Обработка прикрепленного файла (Приоритет 1)
    if file_content and file_name:
        print(f"Обнаружен прикрепленный файл: {file_name}")
        # Создаем "скрытое" системное сообщение
        file_context_message = {
            "role": "system",
            "content": f"Контекст, извлеченный из прикрепленного файла '{file_name}' (используй эту информацию для ответа):\n{file_content}"
        }
        current_messages.append(file_context_message)

    # 4. Создание *видимого* сообщения пользователя
    # (Фронтенд уже показал это пользователю, мы сохраняем это в БД)
    visible_user_message_content = message
    if file_name:
        if visible_user_message_content:
            visible_user_message_content += f"\n\n(Прикреплен файл: {file_name})"
        else:
            visible_user_message_content = f"(Прикреплен файл: {file_name})"
    
    # 5. Обработка ссылок Google Docs (Приоритет 2)
    # Выполняется, ТОЛЬКО если не был прикреплен файл
    urls = URL_REGEX.findall(message) # Ищем в *оригинальном* сообщении
    fetched_link_content = []
    has_google_links = False
    link_context_message = None

    if urls and not file_content: # *** ИЗМЕНЕНИЕ: Проверяем 'not file_content' ***
        print(f"Найдено {len(urls)} URL (файл не прикреплен), загрузка...")
        async with aiohttp.ClientSession() as session:
            tasks = []
            for url in urls:
                tasks.append(_fetch_google_doc_content(session, url))
            
            fetched_contents = await asyncio.gather(*tasks)
            
            for i, content in enumerate(fetched_contents):
                if content: # Если _fetch_google_doc_content вернул что-то (не None)
                    has_google_links = True
                    fetched_link_content.append(f"Контент из {urls[i]}:\n{content}")
        
        if has_google_links:
            combined_link_content = "\n\n---\n\n".join(fetched_link_content)
            # Создаем "скрытое" системное сообщение
            link_context_message = {
                "role": "system",
                "content": f"Контекст, извлеченный из URL-адресов пользователя (используй эту информацию для ответа):\n{combined_link_content}"
            }
            current_messages.append(link_context_message)
            
    elif urls and file_content:
        print("Обнаружены URL, но прикрепленный файл имеет приоритет. URL не будут загружены.")

    # 6. Установка имени чата
    if is_new_chat:
        chat_name = visible_user_message_content[:30]

    # 7. *** ЕДИНЫЙ ШАГ: Анализ, Фильтрация, Решение о поиске ***
    # Используем Llama для принятия всех решений в одном вызове
    # Анализ идет по *видимому* сообщению
    analysis = await _analyze_and_plan(visible_user_message_content, current_messages[-5:])
    
    is_relevant = analysis.get("is_business", False)
    
    # 8. Если фильтр не пройден
    if not is_relevant:
        canned_response = "К сожалению, я могу отвечать только на вопросы, связанные с ведением бизнеса, маркетингом, финансами или юриспруденцией."
        return StreamingResponse(
            _stream_canned_response(canned_response),
            media_type="text/event-stream"
        )

    # 9. Определение "личности" (автоматически из analysis)
    final_personality_key = analysis.get("personality", "default")
    system_prompt = PERSONALITY_PROMPTS.get(final_personality_key, DEFAULT_PROMPT)

    # 10. Выполнение поиска (Приоритет 3)
    search_context = None
    
    # Ищем, ТОЛЬКО если не было файла И не было ссылок GDocs
    if (
        not file_content and not has_google_links and # *** ИЗМЕНЕНИЕ: 'not file_content' ***
        analysis.get("needs_search") and 
        analysis.get("search_query") and 
        analysis.get("num_results") > 0
    ):
        search_context = await _search_duckduckgo(
            analysis.get("search_query"),
            analysis.get("num_results")
        )
    elif analysis.get("needs_search"):
        print("Поиск отменен, так как предоставлен файл или ссылка Google Doc.")


    # 11. Добавляем текущее *видимое* сообщение пользователя в историю для генерации
    current_messages.append({"role": "user", "content": visible_user_message_content})

    # 12. Возвращаем StreamingResponse, который вызывает генератор Cerebras
    return StreamingResponse(
        _stream_cerebras_response(
            system_prompt,
            current_messages, # <-- Уже содержит (history + optional file/link_context + user_message)
            search_context,   # <-- Либо None, либо результаты поиска
            chat_id,
            user_id,
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
            
            # Ищем последнее сообщение от 'user' или 'assistant' для превью
            last_msg_content = None
            for msg in reversed(messages):
                if msg.get("role") in ("user", "assistant"):
                    last_msg_content = msg.get("content")
                    break
            
            last_msg = last_msg_content if last_msg_content else None
            
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
    
    # *** НОВОЕ: Фильтруем "скрытые" системные сообщения перед отправкой в UI ***
    # Мы хотим, чтобы UI отображал только 'user' и 'assistant'
    visible_messages = [
        msg for msg in chat_data["messages"]
        if msg.get("role") in ("user", "assistant")
    ]
    
    return {
        "chat_id": chat_data["chat_id"],
        "name": chat_data["chat_name"],
        "messages": visible_messages # Отправляем только видимые сообщения
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
    uvicorn.run(app, host="0.0.0.0", port=8000)