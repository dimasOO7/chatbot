from fastapi import FastAPI, HTTPException, Form, UploadFile, File, Depends
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
# --- ИЗМЕНЕНИЕ: Используем АСИНХРОННЫЙ клиент OpenAI ---
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import uvicorn
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
import re

import io
import pandas as pd
import docx
from pypdf import PdfReader
from starlette.datastructures import UploadFile as StarletteUploadFile

# --- Новые импорты для безопасности ---
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher()

# --- Regex для deteksi URL ---
URL_REGEX = re.compile(r'https://[\w\.-]+[/\w\.-]*')
DOC_RE = re.compile(r"/document/d/([\w-]+)")
SHEET_RE = re.compile(r"/spreadsheets/d/([\w-]+)")

# --- Загрузка переменных окружения ---
load_dotenv()

# --- Конфигурация API-ключей ---
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")
if not CEREBRAS_API_KEY:
    raise ValueError("Переменная окружения CEREBRAS_API_KEY не установлена.")

# --- ИЗМЕНЕНИЕ: Инициализируем AsyncOpenAI ---
client = AsyncOpenAI(
    api_key=CEREBRAS_API_KEY,
    base_url="https://api.cerebras.ai/v1"
)

CLASSIFY_MODEL_ID = "llama-3.3-70b"
GENERATE_MODEL_ID = "gpt-oss-120b"

# --- Инициализация приложения ---
app = FastAPI(
    title="API чата Cerebras (Async SQLite + Поиск + Auth)",
    description="Асинхронный чат с историей, авто-классификацией, поиском DuckDuckGo и JWT аутентификацией.",
)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Настройка базы данных ---
DB_NAME = "database.db"

@app.on_event("startup")
async def startup_event():
    app.state.db = await aiosqlite.connect(DB_NAME)
    app.state.db.row_factory = aiosqlite.Row
    
    # --- Таблица чатов ---
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
    
    # *** ИЗМЕНЕНИЕ: Новая таблица пользователей ***
    await app.state.db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL
        )
    ''')
    await app.state.db.commit()
    print("✅ База данных инициализирована (с таблицей users).")

@app.on_event("shutdown")
async def shutdown_event():
    await app.state.db.close()
    print("🧹 Соединение с базой закрыто.")

# --- ********************************* ---
# --- *** НОВЫЙ БЛОК: АУТЕНТИФИКАЦИЯ *** ---
# --- ********************************* ---

# --- Конфигурация безопасности ---
SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("Переменная окружения JWT_SECRET_KEY не установлена. (e.g., openssl rand -hex 32)")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 часа

# Контекст для хеширования паролей


# Схема OAuth2 (для Depends)
# /token - это эндпоинт, который мы создадим для получения токена
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Модели Pydantic для аутентификации ---
class Token(BaseModel):
    access_token: str
    token_type: str
    username: str # *** ИЗМЕНЕНИЕ: Добавляем имя пользователя в ответ

class TokenData(BaseModel):
    username: Optional[str] = None

class User(BaseModel):
    username: str

class UserInDB(User):
    hashed_password: str

class UserCreate(BaseModel):
    username: str
    password: str

# --- Утилиты аутентификации ---

# --- ИЗМЕНЕНИЕ: Это БЛОКИРУЮЩИЕ функции (CPU-bound) ---
# Мы не делаем их 'async def', но будем вызывать их через to_thread
def verify_password(plain_password, hashed_password):
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except VerifyMismatchError:
        return False

def get_password_hash(password):
    return ph.hash(password)
# --- Конец блокирующих функций ---


async def get_user_from_db(username: str) -> Optional[UserInDB]:
    db = get_db()
    async with db.execute("SELECT username, hashed_password FROM users WHERE username = ?", (username,)) as cursor:
        user_row = await cursor.fetchone()
    if user_row:
        return UserInDB(**user_row)
    return None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- Зависимость (Dependency) для защиты эндпоинтов ---
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Декодирует JWT токен, извлекает ID пользователя (sub)
    и возвращает данные пользователя.
    Вызовет 401, если токен невалиден.
    """
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # --- ИЗМЕНЕНИЕ: Выполняем быструю (sync) CPU-операцию в to_thread
        # Хотя JWT быстр, это "полностью" асинхронный подход
        payload = await asyncio.to_thread(
            jwt.decode, token, SECRET_KEY, [ALGORITHM]
        )
        
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    user = await get_user_from_db(token_data.username)
    if user is None:
        raise credentials_exception
    
    # *** ИЗМЕНЕНИЕ: Возвращаем словарь с именем пользователя ***
    # Это позволит нам использовать 'user['username']' в защищенных маршрутах
    return {"username": user.username}

# --- *********************************** ---
# --- *** КОНЕЦ БЛОКА АУТЕНТИФИКАЦИИ *** ---
# --- *********************************** ---


# --- Системные промпты (Личности) ---
SEARCH_INSTRUCTION = (
    "\n\n**Важное правило:** Если в начале твоего контекста предоставлены 'Результаты Поиска' или 'Контекст, извлеченный из URL' "
    "или 'Контекст, извлеченный из прикрепленного файла', "
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
# ... (Остальные PERSONALITY_PROMPTS без изменений) ...
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

# --- Модели ---
class ChatHistoryRequest(BaseModel):
    # *** ИЗМЕНЕНИЕ: user_id больше не нужен, мы берем его из токена ***
    chat_id: str

# *** ИЗМЕНЕНИЕ: UserIdRequest больше не нужен, мы используем токен ***
# class UserIdRequest(BaseModel):
#     user_id: str

# --- Утилита для доступа к БД ---
def get_db():
    return app.state.db

# --- Функции работы с БД ---
async def _get_chat_from_db(chat_id: str, user_id: str) -> Dict[str, Any] | None:
    db = get_db()
    # *** ИЗМЕНЕНИЕ: Добавлена проверка user_id при поиске чата ***
    async with db.execute(
        "SELECT user_id, chat_name, messages FROM chats WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
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
    updated_at = datetime.now().isoformat()

    if is_new_chat:
        await db.execute("""
            INSERT INTO chats (user_id, chat_id, chat_name, messages, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, chat_id, chat_name, messages_json, updated_at))
    else:
        # *** ИЗМЕНЕНИЕ: Добавлена проверка user_id при обновлении ***
        await db.execute("""
            UPDATE chats SET chat_name = ?, messages = ?, updated_at = ?
            WHERE chat_id = ? AND user_id = ?
        """, (chat_name, messages_json, updated_at, chat_id, user_id))

    await db.commit()

# --- Логика фильтрации и стриминга ---
# ... (Функции _analyze_and_plan, _fetch_google_doc_content, _fetch_and_parse, _search_duckduckgo, _stream_canned_response - без изменений) ...
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
        date=datetime.now().strftime("%d.%m.%Y"),
        history=history_str,
        query=user_query
    )
    
    try:
        # --- ИЗМЕНЕНИЕ: Используем 'await' для асинхронного клиента ---
        response = await client.chat.completions.create(
            model=CLASSIFY_MODEL_ID, # Используем Llama
            messages=[
                {"role": "system", "content": "Ты — ИИ-анализатор. Твоя задача — проанализировать запрос и вернуть ТОЛЬКО JSON-объект с планом действий."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=400 # Увеличим, т.к. промпт и JSON стали сложнее
        )
        
        content = response.choices[0].message.content.strip() # type: ignore
        
        if content.startswith("```"):
            try:
                json_part = content.split("\n", 1)[1]
                content = json_part.rsplit("\n```", 1)[0]
            except (IndexError, ValueError):
                print(f"Ошибка парсинга JSON-блока в _analyze_and_plan: {content}")
                pass
            
        print(f"Cerebras (Analysis/Plan) Response: {content}")
        data = json.loads(content)
        
        is_business = bool(data.get("is_business", False))
        personality = data.get("personality", "default")
        needs_search = bool(data.get("needs_search", False))
        search_query = data.get("search_query")
        num_results = int(data.get("num_results", 0))

        if not is_business:
            return {
                "is_business": False,
                "personality": "default",
                "needs_search": False,
                "search_query": None,
                "num_results": 0
            }
        
        if needs_search and not search_query:
            needs_search = False
            num_results = 0

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
        return {
            "is_business": False,
            "personality": "default",
            "needs_search": False,
            "search_query": None,
            "num_results": 0
        }

async def _fetch_google_doc_content(session: aiohttp.ClientSession, url: str) -> str | None:
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
    
    doc_match = DOC_RE.search(url)
    sheet_match = SHEET_RE.search(url)
    
    export_url = None
    
    if doc_match:
        doc_id = doc_match.group(1)
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    elif sheet_match:
        sheet_id = sheet_match.group(1)
        export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"

    if not export_url:
        return None 

    MAX_DOC_LENGTH = 8000
    
    try:
        print(f"Загрузка Google Doc/Sheet: {export_url}")
        async with session.get(export_url, timeout=7, headers=headers) as response:
            if response.status != 200:
                return f"[Не удалось загрузить URL: {url} (статус: {response.status})]"
            
            content_bytes = await response.read()
            text_content = ""
            
            try:
                text_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_content = content_bytes.decode('windows-1251')
                except Exception as e:
                    return f"[Не удалось декодировать контент из {url}: {e}]"
            
            return text_content[:MAX_DOC_LENGTH] + "..." if len(text_content) > MAX_DOC_LENGTH else text_content

    except asyncio.TimeoutError:
        return f"[Не удалось загрузить URL: {url} (тайм-аут)]"
    except Exception as e:
        print(f"Ошибка при загрузке Google Doc {url}: {e}")
        return f"[Ошибка при загрузке URL {url}: {str(e)}]"

async def _fetch_and_parse(session: aiohttp.ClientSession, url: str) -> str:
    MAX_TEXT_LENGTH = 10000 
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        
        async with session.get(url, timeout=5, headers=headers) as response:
            if response.status != 200:
                return f"Не удалось загрузить (статус: {response.status})"
            
            if 'text/html' not in response.headers.get('Content-Type', ''):
                 return "Контент не является HTML-страницей."
                 
            html = await response.text()
            
            # --- ИЗМЕНЕНИЕ: BeautifulSoup - блокирующая операция. Выполняем в to_thread ---
            def parse_html(html_content):
                soup = BeautifulSoup(html_content, 'html.parser')
                for script_or_style in soup(["script", "style"]):
                    script_or_style.decompose()
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                return '\n'.join(chunk for chunk in chunks if chunk)

            text = await asyncio.to_thread(parse_html, html)
            # --- Конец изменения ---
            
            if not text:
                return "Не удалось извлечь текст из HTML."
            
            return text[:MAX_TEXT_LENGTH] + "..." if len(text) > MAX_TEXT_LENGTH else text

    except asyncio.TimeoutError:
        return "Не удалось загрузить (тайм-аут)."
    except Exception as e:
        print(f"Ошибка при загрузке {url}: {e}")
        return f"Ошибка при загрузке контента: {str(e)}"

async def _search_duckduckgo(query: str, max_results: int) -> str:
    if not 1 <= max_results <= 5:
        print(f"Некорректное кол-во результатов ({max_results}), установлено 3.")
        max_results = 3
        
    print(f"Выполнение поиска ({max_results} стр.): {query}")
    results_data = []
    
    try:
        async with aDDGS() as ddgs:
            results = await ddgs.text(query, max_results=max_results)
            
            if not results:
                return "Результаты Поиска: Не найдено."
            
            results_data = results 
            
    except Exception as e:
        print(f"Ошибка поиска DuckDuckGo: {e}")
        return "Результаты Поиска: Ошибка при выполнении."

    formatted_results = ["Результаты Поиска (используй их для ответа, в конце ответа приведи источники):"]
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for r in results_data:
            tasks.append(_fetch_and_parse(session, r['href']))
        
        fetched_contents = await asyncio.gather(*tasks)

        for i, (r, fetched_text) in enumerate(zip(results_data, fetched_contents)):
            final_content = fetched_text
            if "Не удалось" in fetched_text or "Ошибка" in fetched_text or "не является HTML" in fetched_text or "Не удалось извлечь" in fetched_text:
                 final_content = r['body'] 
            
            formatted_results.append(
                f"Источник {i+1}: [URL: {r['href']}] [ТЕКСТ: {final_content}]"
            )
    
    return "\n".join(formatted_results)

async def _stream_canned_response(message: str) -> AsyncGenerator[str, None]:
    yield message
    await asyncio.sleep(0)


async def _stream_cerebras_response(
    system_prompt: Dict[str, str],
    current_messages: List[Dict[str, str]],
    search_context: str | None,
    chat_id: str,
    user_id: str, # *** ИЗМЕНЕНИЕ: user_id (username) передается из токена ***
    chat_name: str,
    is_new_chat: bool
) -> AsyncGenerator[str, None]:
    full_reply_content = []
    final_messages = [system_prompt]
    
    if search_context:
        final_messages.append({"role": "system", "content": search_context})
    
    final_messages.extend(current_messages)
    
    try:
        # --- ИЗМЕНЕНИЕ: Используем 'await' для асинхронного клиента ---
        stream = await client.chat.completions.create(
            model=GENERATE_MODEL_ID,
            messages=final_messages, # type: ignore
            stream=True
        )
        
        # --- ИЗМЕНЕНИЕ: Используем 'async for' для асинхронного стрима ---
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                full_reply_content.append(content)
                yield content

    except Exception as e:
        print(f"Ошибка API Cerebras (стрим): {e}")
        yield f"Ошибка API: {str(e)}"
    
    finally:
        full_message = "".join(full_reply_content)
        
        if full_message:
            current_messages.append({"role": "assistant", "content": full_message})
            
            await _update_chat_in_db(
                chat_id=chat_id,
                user_id=user_id, # *** ИЗМЕНЕНИЕ: Используем user_id из токена ***
                chat_name=chat_name,
                messages=current_messages,
                is_new_chat=is_new_chat
            )


# --- ИЗМЕНЕНИЕ: Выносим блокирующие (CPU/IO) функции парсинга ---
# Они будут вызваны в _read_uploaded_file через asyncio.to_thread

def _parse_xlsx(content_bytes: bytes) -> str:
    """Блокирующая функция парсинга XLSX."""
    bytes_io = io.BytesIO(content_bytes)
    xls = pd.ExcelFile(bytes_io, engine='openpyxl')
    all_sheets = []
    for sheet_name in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        all_sheets.append(f"--- Лист: {sheet_name} ---\n{df.to_csv(index=False)}")
    return "\n\n".join(all_sheets)

def _parse_docx(content_bytes: bytes) -> str:
    """Блокирующая функция парсинга DOCX."""
    bytes_io = io.BytesIO(content_bytes)
    doc = docx.Document(bytes_io)
    all_paragraphs = [p.text for p in doc.paragraphs]
    return "\n".join(all_paragraphs)

def _parse_pdf(content_bytes: bytes) -> str:
    """Блокирующая функция парсинга PDF."""
    bytes_io = io.BytesIO(content_bytes)
    reader = PdfReader(bytes_io)
    all_pages = [page.extract_text() for page in reader.pages if page.extract_text()]
    return "\n\n--- Новая страница ---\n\n".join(all_pages)

# --- Конец блокирующих функций парсинга ---


MAX_FILE_CONTEXT_LENGTH = 15000
async def _read_uploaded_file(file: UploadFile) -> str:
    filename = file.filename or ""
    
    if '.' not in filename:
        extension = 'txt'
    else:
        extension = filename.rsplit('.', 1)[-1].lower()

    print(f"Парсинг файла: {filename} (тип: {extension})")
    
    # file.read() уже асинхронный
    content_bytes = await file.read()
    text_content = None

    try:
        # --- ИЗМЕНЕНИЕ: Выполняем блокирующий парсинг в thread pool ---
        if extension == 'xlsx':
            text_content = await asyncio.to_thread(_parse_xlsx, content_bytes)
        
        elif extension == 'docx':
            text_content = await asyncio.to_thread(_parse_docx, content_bytes)

        elif extension == 'pdf':
            text_content = await asyncio.to_thread(_parse_pdf, content_bytes)
        
        elif extension in ('txt', 'csv', 'html') or '.' not in filename:
            # Декодирование - быстрая операция, можно оставить в основном потоке
            try:
                text_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                text_content = content_bytes.decode('windows-1251')
            
            if extension == 'html':
                # BeautifulSoup может быть медленным, лучше в to_thread
                def parse_html_text(html_text):
                    soup = BeautifulSoup(html_text, 'html.parser')
                    return soup.get_text(separator="\n", strip=True)
                
                text_content = await asyncio.to_thread(parse_html_text, text_content)
            
        else:
            # Попытка декодировать неизвестные типы как текст
            try:
                text_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_content = content_bytes.decode('windows-1251')
                except UnicodeDecodeError:
                    print(f"Файл {filename} имеет неизвестное расширение и не является текстом.")
                    return None 

    except Exception as e:
        print(f"Ошибка парсинга файла {filename} (ext: {extension}): {e}")
        return None

    if text_content is None:
        return None
        
    if len(text_content) > MAX_FILE_CONTEXT_LENGTH:
        text_content = text_content[:MAX_FILE_CONTEXT_LENGTH] + \
                       f"\n... [СОДЕРЖИМОЕ ФАЙЛА '{filename}' ОБРЕЗАНО] ..."
    
    return text_content
# --- Конец _read_uploaded_file ---


# --- Маршруты ---

@app.get("/", response_class=HTMLResponse)
async def index():
    # Этот маршрут теперь просто отдает HTML.
    # Клиент (JS) сам решит, показывать модальное окно или нет.
    return FileResponse("templates/index.html", media_type="text/html")

# --- *** НОВЫЕ МАРШРУТЫ АУТЕНТИФИКАЦИИ *** ---

@app.post("/register", status_code=201)
async def register_user(user_create: UserCreate):
    """
    Регистрирует нового пользователя.
    """
    db = get_db()
    existing_user = await get_user_from_db(user_create.username)
    if existing_user:
        raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
    
    # --- ИЗМЕНЕНИЕ: Хеширование - CPU-bound, выполняем в to_thread ---
    hashed_password = await asyncio.to_thread(
        get_password_hash, user_create.password
    )
    # --- Конец изменения ---
    
    await db.execute(
        "INSERT INTO users (username, hashed_password) VALUES (?, ?)",
        (user_create.username, hashed_password)
    )
    await db.commit()
    
    return {"message": "Пользователь успешно зарегистрирован"}

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Принимает username и password из формы,
    проверяет их и возвращает JWT токен.
    """
    user = await get_user_from_db(form_data.username)
    
    # --- ИЗМЕНЕНИЕ: Проверка пароля - CPU-bound, выполняем в to_thread ---
    is_verified = False
    if user:
        is_verified = await asyncio.to_thread(
            verify_password, form_data.password, user.hashed_password
        )
    # --- Конец изменения ---

    if not user or not is_verified:
        raise HTTPException(
            status_code=401,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # --- ИЗМЕНЕНИЕ: Создание JWT - быстрая CPU-операция, тоже в to_thread ---
    access_token = await asyncio.to_thread(
        create_access_token, data={"sub": user.username}
    )
    # --- Конец изменения ---
    
    # *** ИЗМЕНЕНИЕ: Возвращаем имя пользователя вместе с токеном ***
    return {
        "access_token": access_token, 
        "token_type": "bearer", 
        "username": user.username
    }

# --- *** ЗАЩИЩЕННЫЕ МАРШРУТЫ *** ---

@app.post("/send_message_stream")
async def send_message_stream(
    # *** ИЗМЕНЕНИЕ: user_id УДАЛЕН из Form, добавлен current_user из токена ***
    current_user: dict = Depends(get_current_user),
    message: str = Form(""),
    chat_id: str = Form(...),
    file: Optional[UploadFile] = File(None)
):
    """
    Обрабатывает сообщение, выполняет анализ, поиск (если нужно) и стримит ответ.
    Теперь защищено: user_id берется из JWT токена.
    """
    
    # *** ИЗМЕНЕНИЕ: user_id (username) берется из токена ***
    user_id = current_user['username']
    
    # 1. Чтение файла
    file_content: str | None = None
    file_name: str | None = None

    if file:
        file_name = file.filename
        file_content = await _read_uploaded_file(file) 
    
    if not message and not file_content:
        raise HTTPException(status_code=400, detail="Сообщение или файл должны присутствовать.")
        
    # 2. Получение данных чата
    # *** ИЗМЕНЕНИЕ: _get_chat_from_db теперь также требует user_id для безопасности ***
    chat_data = await _get_chat_from_db(chat_id, user_id)
    is_new_chat = chat_data is None

    if is_new_chat:
        current_messages = []
    else:
        chat_name = chat_data["chat_name"]
        current_messages = chat_data["messages"]
        
    # 3. Обработка прикрепленного файла
    if file_content and file_name:
        print(f"Обнаружен прикрепленный файл: {file_name}")
        file_context_message = {
            "role": "system",
            "content": f"Контекст, извлеченный из прикрепленного файла '{file_name}' (используй эту информацию для ответа):\n{file_content}"
        }
        current_messages.append(file_context_message)

    # 4. Создание видимого сообщения пользователя
    visible_user_message_content = message
    if file_name:
        if visible_user_message_content:
            visible_user_message_content += f"\n\n(Прикреплен файл: {file_name})"
        else:
            visible_user_message_content = f"(Прикреплен файл: {file_name})"
    
    # 5. Обработка ссылок Google Docs
    urls = URL_REGEX.findall(message)
    fetched_link_content = []
    has_google_links = False
    link_context_message = None

    if urls and not file_content: 
        print(f"Найдено {len(urls)} URL (файл не прикреплен), загрузка...")
        async with aiohttp.ClientSession() as session:
            tasks = []
            for url in urls:
                tasks.append(_fetch_google_doc_content(session, url))
            
            fetched_contents = await asyncio.gather(*tasks)
            
            for i, content in enumerate(fetched_contents):
                if content: 
                    has_google_links = True
                    fetched_link_content.append(f"Контент из {urls[i]}:\n{content}")
        
        if has_google_links:
            combined_link_content = "\n\n---\n\n".join(fetched_link_content)
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

    # 7. Анализ, Фильтрация, Решение о поиске
    analysis = await _analyze_and_plan(visible_user_message_content, current_messages[-5:])
    
    is_relevant = analysis.get("is_business", False)
    
    # 8. Если фильтр не пройден
    if not is_relevant:
        canned_response = "К сожалению, я могу отвечать только на вопросы, связанные с ведением бизнеса, маркетингом, финансами или юриспруденцией."
        return StreamingResponse(
            _stream_canned_response(canned_response),
            media_type="text/event-stream"
        )

    # 9. Определение "личности"
    final_personality_key = analysis.get("personality", "default")
    # --- ИЗМЕНЕНИЕ: Получаем базовый промпт ---
    base_system_prompt = PERSONALITY_PROMPTS.get(final_personality_key, DEFAULT_PROMPT)
    
    # --- ИЗМЕНЕНИЕ: Внедряем имя пользователя (логин) в промпт ---
    # Создаем *копию* словаря, чтобы не изменить оригинал
    system_prompt = base_system_prompt.copy()
    user_name = current_user['username'] # user_id это и есть username
    # Добавляем инструкцию в начало
    system_prompt['content'] = (
        f"Ты общаешься с пользователем по имени '{user_name}'. "
        f"Если это уместно, ты можешь обращаться к нему по имени (например, 'Здраствуйте {user_name}'). "
        f"{system_prompt['content']}"
    )
    # --- Конец изменения ---


    # 10. Выполнение поиска
    search_context = None
    if (
        not file_content and not has_google_links and
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

    # 11. Добавляем текущее *видимое* сообщение
    current_messages.append({"role": "user", "content": visible_user_message_content})

    # 12. Возвращаем StreamingResponse
    return StreamingResponse(
        _stream_cerebras_response(
            system_prompt, # Передаем уже измененный промпт
            current_messages,
            search_context,
            chat_id,
            user_id, # *** ИЗМЕНЕНИЕ: Передаем user_id из токена ***
            chat_name,
            is_new_chat
        ),
        media_type="text/event-stream"
    )


@app.get("/get_chats") # *** ИЗМЕНЕНИЕ: Меняем на GET, т.к. user_id в токене ***
async def get_chats(current_user: dict = Depends(get_current_user)):
    # *** ИЗМЕНЕНИЕ: req (UserIdRequest) больше не нужен ***
    user_id = current_user['username']
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id не может быть пустым.")

    db = get_db()
    chats_list = []
    async with db.execute("""
        SELECT chat_id, chat_name, messages, updated_at
        FROM chats WHERE user_id = ?
        ORDER BY updated_at DESC
    """, (user_id,)) as cursor:
        async for row in cursor:
            messages = json.loads(row["messages"]) if row["messages"] else []
            
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
async def get_chat_history(
    req: ChatHistoryRequest, 
    current_user: dict = Depends(get_current_user)
):
    # *** ИЗМЕНЕНИЕ: user_id из токена ***
    user_id = current_user['username']
    
    # *** ИЗМЕНЕНИЕ: _get_chat_from_db теперь проверяет user_id ***
    chat_data = await _get_chat_from_db(req.chat_id, user_id)
    if not chat_data:
        # Не нужно проверять (chat_data["user_id"] != user_id), т.к.
        # _get_chat_from_db вернет None, если user_id не совпадет
        raise HTTPException(status_code=404, detail="Чат не найден или не принадлежит пользователю.")
    
    visible_messages = [
        msg for msg in chat_data["messages"]
        if msg.get("role") in ("user", "assistant")
    ]
    
    return {
        "chat_id": chat_data["chat_id"],
        "name": chat_data["chat_name"],
        "messages": visible_messages
    }

@app.post("/delete_chat")
async def delete_chat(
    req: ChatHistoryRequest, 
    current_user: dict = Depends(get_current_user)
):
    # *** ИЗМЕНЕНИЕ: user_id из токена ***
    user_id = current_user['username']
    
    if not req.chat_id:
        raise HTTPException(status_code=400, detail="chat_id обязателен.")

    db = get_db()
    
    # *** ИЗМЕНЕНИЕ: Проверяем, что чат принадлежит пользователю ПЕРЕД удалением ***
    async with db.execute(
        "SELECT user_id FROM chats WHERE chat_id = ?", (req.chat_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Чат не найден или не принадлежит пользователю.")
    
    # Если проверка пройдена, удаляем
    await db.execute("DELETE FROM chats WHERE chat_id = ?", (req.chat_id,))
    await db.commit()
    
    return {"status": "ok", "message": "Чат удален"}

# --- Точка входа ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)