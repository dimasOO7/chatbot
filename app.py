# *** ИЗМЕНЕНИЕ: Новые импорты для JWT, OAuth2, Pydantic, Hashing ***
from fastapi import FastAPI, HTTPException, Form, UploadFile, File, Depends
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from openai import OpenAI
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

# --- Новые импорты для Аутентификации ---
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone

# --- Regex для deteksi URL ---
URL_REGEX = re.compile(r'https://[\w\.-]+[/\w\.-]*')
DOC_RE = re.compile(r"/document/d/([\w-]+)")
SHEET_RE = re.compile(r"/spreadsheets/d/([\w-]+)")

# --- Загрузка переменных окружения ---
load_dotenv()

CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")
if not CEREBRAS_API_KEY:
    raise ValueError("Переменная окружения CEREBRAS_API_KEY не установлена.")

client = OpenAI(
    api_key=CEREBRAS_API_KEY,
    base_url="https://api.cerebras.ai/v1"
)

CLASSIFY_MODEL_ID = "llama-3.3-70b"
GENERATE_MODEL_ID = "gpt-oss-120b"

# *** ИЗМЕНЕНИЕ: Настройки безопасности JWT ***
# Создайте свой 'openssl rand -hex 32'
SECRET_KEY = os.environ.get("SECRET_KEY", "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 1 день

# --- Инициализация приложения ---
app = FastAPI(
    title="API чата Cerebras (JWT Auth)",
    description="Асинхронный чат с JWT аутентификацией, историей, авто-классификацией и поиском.",
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
    
    await app.state.db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    await app.state.db.commit()
    print("✅ База данных инициализирована (с таблицей users).")

@app.on_event("shutdown")
async def shutdown_event():
    await app.state.db.close()
    print("🧹 Соединение с базой закрыто.")

# --- Системные промпты (Личности) ---
# (Без изменений, SEARCH_INSTRUCTION по-прежнему использует {nickname})
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
    "\n\n**О пользователе:** Ты общаешься с пользователем по имени **{nickname}**. "
    "Будь вежлив и можешь обращаться к нему по имени, если это уместно (например, 'Здравствуйте, {nickname}!' или 'Рад помочь, {nickname}.')."
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
        "content": "Вы — PNIbot, помощник по юридическим вопросам. Вы предоставляете ОБЩУЮ информацию по регистрации бизнеса, налогам, контрактам и интеллектуальной собственности. ВАЖНО: Всегда напоминайте пользователю (его зовут {nickname}), что вы не даете юридических консультаций (legal advice) и что для решения конкретной проблемы необходимо обратиться к квалифицированному юристу." + SEARCH_INSTRUCTION
    },
    "analyst": {
        "role": "system",
        "content": "Вы — PNIbot, бизнес-аналитик. Вы помогаете анализировать бизнес-идеи, оценивать рыночные ниши, составлять фин. модели и SWOT-анализ. Фокусируйтесь на данных, цифрах и структурированных ответах (например, списки, таблицы)." + SEARCH_INSTRUCTION
    }
}
# (ANALYSIS_PLAN_PROMPT_TEMPLATE без изменений)
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

# --- Модели Pydantic ---

class AuthRequest(BaseModel):
    login: str
    pass_hash: str

# *** ИЗМЕНЕНИЕ: Модели для JWT ***
class Token(BaseModel):
    access_token: str
    token_type: str
    nickname: str

class TokenData(BaseModel):
    login: Optional[str] = None

class User(BaseModel):
    login: str
# *** КОНЕЦ ИЗМЕНЕНИЯ ***

# *** ИЗМЕНЕНИЕ: Модели запросов больше не содержат user_id ***
class ChatHistoryRequest(BaseModel):
    chat_id: str

# (UserIdRequest больше не нужен)

# --- Утилита для доступа к БД ---
def get_db():
    return app.state.db

# --- Функции работы с БД ---
# (Без изменений: _get_chat_from_db, _update_chat_in_db)
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
    updated_at = datetime.now(timezone.utc).isoformat()

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
    
# *** ИЗМЕНЕНИЕ: Функции для JWT Аутентификации ***
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=401,
        detail="Не удалось проверить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        login: str = payload.get("sub")
        if login is None:
            raise credentials_exception
        token_data = TokenData(login=login)
    except JWTError:
        raise credentials_exception
    
    # (В реальном приложении можно было бы еще раз проверить юзера в БД)
    # db = get_db() ...
    
    if token_data.login is None:
        raise credentials_exception
    
    return User(login=token_data.login)
# *** КОНЕЦ ИЗМЕНЕНИЯ ***

# --- Логика фильтрации и стриминга ---

# (Без изменений: _analyze_and_plan)
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
        date=datetime.now(timezone.utc).strftime("%d.%m.%Y"),
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
            max_tokens=400
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

# (Без изменений: _fetch_google_doc_content, _fetch_and_parse, _search_duckduckgo, _stream_canned_response)
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
    MAX_DOC_LENGTH = 3000
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
            soup = BeautifulSoup(html, 'html.parser')
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
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

# (Без изменений: _stream_cerebras_response, _read_uploaded_file)
async def _stream_cerebras_response(
    system_prompt: Dict[str, str],
    current_messages: List[Dict[str, str]],
    search_context: str | None,
    chat_id: str,
    user_id: str,
    chat_name: str,
    is_new_chat: bool
) -> AsyncGenerator[str, None]:
    full_reply_content = []
    final_messages = [system_prompt]
    if search_context:
        final_messages.append({"role": "system", "content": search_context})
    final_messages.extend(current_messages)
    
    try:
        stream = client.chat.completions.create(
            model=GENERATE_MODEL_ID,
            messages=final_messages, # type: ignore
            stream=True
        )
        for chunk in stream:
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
                user_id=user_id,
                chat_name=chat_name,
                messages=current_messages,
                is_new_chat=is_new_chat
            )

MAX_FILE_CONTEXT_LENGTH = 15000
async def _read_uploaded_file(file: UploadFile) -> str:
    filename = file.filename or ""
    if '.' not in filename:
        extension = 'txt'
    else:
        extension = filename.rsplit('.', 1)[-1].lower()
    print(f"Парсинг файла: {filename} (тип: {extension})")
    content_bytes = await file.read()
    text_content = None
    try:
        if extension == 'xlsx':
            bytes_io = io.BytesIO(content_bytes)
            xls = pd.ExcelFile(bytes_io, engine='openpyxl')
            all_sheets = []
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
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
            try:
                text_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                text_content = content_bytes.decode('windows-1251')
            if extension == 'html':
                soup = BeautifulSoup(text_content, 'html.parser')
                text_content = soup.get_text(separator="\n", strip=True)
        else:
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
    
# --- Маршруты ---
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("templates/index.html", media_type="text/html")

# *** ИЗМЕНЕНИЕ: Маршруты авторизации теперь возвращают JWT токен ***

@app.post("/register", response_model=Token)
async def register_user(req: AuthRequest):
    db = get_db()
    async with db.execute("SELECT id FROM users WHERE login = ?", (req.login,)) as cursor:
        existing_user = await cursor.fetchone()
    if existing_user:
        raise HTTPException(status_code=400, detail="Этот логин уже занят.")
    try:
        await db.execute(
            "INSERT INTO users (login, password_hash) VALUES (?, ?)",
            (req.login, req.pass_hash)
        )
        await db.commit()
    except Exception as e:
        print(f"Ошибка регистрации: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка сервера при регистрации: {e}")
    
    # *** НОВОЕ: Сразу логиним и выдаем токен ***
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": req.login}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "nickname": req.login}


@app.post("/login", response_model=Token)
async def login_user(req: AuthRequest):
    db = get_db()
    async with db.execute("SELECT password_hash FROM users WHERE login = ?", (req.login,)) as cursor:
        user = await cursor.fetchone()
        
    if not user or user["password_hash"] != req.pass_hash:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль.")
        
    # *** НОВОЕ: Выдаем токен ***
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": req.login}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "nickname": req.login}
    
# *** КОНЕЦ ИЗМЕНЕНИЙ В АВТОРИЗАЦИИ ***


# *** ИЗМЕНЕНИЕ: /send_message_stream теперь защищен и не принимает user_id ***
@app.post("/send_message_stream")
async def send_message_stream(
    message: str = Form(""),
    chat_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user) # <-- НОВЫЙ ЗАЩИЩЕННЫЙ ПАРАМЕТР
):
    """
    Обрабатывает сообщение (из FormData), выполняет единый анализ (фильтр + поиск),
    выполняет поиск (если нужно) и стримит ответ.
    Использует `current_user` из токена.
    """
    
    # *** НОВОЕ: user_id берется из токена ***
    user_id = current_user.login
    
    file_content: str | None = None
    file_name: str | None = None

    if file:
        file_name = file.filename
        file_content = await _read_uploaded_file(file)
    
    if not message and not file_content:
        raise HTTPException(status_code=400, detail="Сообщение или файл должны присутствовать (или файл не удалось прочитать).")
        
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id обязателен.")

    chat_data = await _get_chat_from_db(chat_id)
    is_new_chat = chat_data is None

    if is_new_chat:
        current_messages = []
    else:
        # *** ПРОВЕРКА БЕЗОПАСНОСТИ: Убедимся, что юзер владеет чатом ***
        if chat_data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Доступ к чату запрещен.")
        chat_name = chat_data["chat_name"]
        current_messages = chat_data["messages"]
        
    # (Дальнейшая логика _send_message_stream без изменений, 
    #  т.к. user_id теперь корректно установлен)

    # 3. Обработка прикрепленного файла
    if file_content and file_name:
        print(f"Обнаружен прикрепленный файл: {file_name}")
        file_context_message = {
            "role": "system",
            "content": f"Контекст, извлеченный из прикрепленного файла '{file_name}' (используй эту информацию для ответа):\n{file_content}"
        }
        current_messages.append(file_context_message)

    # 4. Создание *видимого* сообщения пользователя
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
    
    # *** ИЗМЕНЕНИЕ: user_id - это и есть nickname ***
    base_system_prompt = PERSONALITY_PROMPTS.get(final_personality_key, DEFAULT_PROMPT)
    formatted_content = base_system_prompt["content"].format(nickname=user_id)
    system_prompt = {"role": base_system_prompt["role"], "content": formatted_content}

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
            system_prompt,
            current_messages,
            search_context,
            chat_id,
            user_id, # <-- Передаем user_id из токена
            chat_name,
            is_new_chat
        ),
        media_type="text/event-stream"
    )

# *** ИЗМЕНЕНИЕ: /get_chats теперь GET и защищен ***
@app.get("/get_chats")
async def get_chats(current_user: User = Depends(get_current_user)):
    user_id = current_user.login
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

# *** ИЗМЕНЕНИЕ: /get_chat_history защищен и не принимает user_id ***
@app.post("/get_chat_history")
async def get_chat_history(req: ChatHistoryRequest, current_user: User = Depends(get_current_user)):
    user_id = current_user.login
    chat_data = await _get_chat_from_db(req.chat_id)
    
    if not chat_data or chat_data["user_id"] != user_id:
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

# *** ИZМЕНЕНИЕ: /delete_chat защищен и не принимает user_id ***
@app.post("/delete_chat")
async def delete_chat(req: ChatHistoryRequest, current_user: User = Depends(get_current_user)):
    user_id = current_user.login
    db = get_db()
    
    async with db.execute(
        "SELECT user_id FROM chats WHERE chat_id = ?", (req.chat_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row or row["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Чат не найден или не принадлежит пользователю.")
    
    await db.execute("DELETE FROM chats WHERE chat_id = ?", (req.chat_id,))
    await db.commit()
    
    return {"status": "ok", "message": "Чат удален"}

# --- Точка входа ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)