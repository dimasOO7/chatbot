// --- Глобальные переменные ---
let currentChatId = null; // ID текущего чата
let chats = []; // Массив всех чатов
let userId = localStorage.getItem('chat_user_id'); // ID пользователя из локального хранилища
let isSidebarCollapsed = false;
let currentFile = null; // *** ИЗМЕНЕНИЕ: Хранит выбранный файл ***



// --- Переменные для управления стримингом ---
let isStreaming = false; // Флаг, показывающий, идёт ли сейчас стриминг ответа
let activeFetchController = null; // Контроллер для отмены запроса, если нужно

// --- Генерация уникального ID пользователя ---
if (!userId || userId === "") {
    // Если ID не задан, создаём его случайным образом
    if (typeof window.crypto.randomUUID === 'function') {
        userId = window.crypto.randomUUID(); // Современный способ
    } else {
        userId = 'temp-user-' + Date.now(); // Резервный способ
    }
    localStorage.setItem('chat_user_id', userId); // Сохраняем в локальное хранилище
}
console.log("User ID:", userId); // Выводим ID в консоль для проверки

// --- Инициализация приложения ---
document.addEventListener('DOMContentLoaded', async () => {
    // 1. Загружаем список чатов с сервера
    await loadChats();
    
    // *** ИЗМЕНЕНИЕ: Логика 'personality' удалена ***
    
    // 2. Выбираем самый новый чат или создаём новый
    if (chats.length > 0) {
        await setCurrentChat(chats[0].id); // Устанавливаем первый чат
    } else {
        createNewChat(); // Если чатов нет — создаём новый
    }
});

// --- Загрузка списка чатов с сервера ---
async function loadChats() {
    try {
        // Отправляем POST-запрос на сервер для получения списка чатов
        const response = await fetch('/get_chats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });

        if (!response.ok) {
            throw new Error('Не удалось загрузить чаты');
        }

        const data = await response.json(); // Получаем данные в формате JSON
        chats = data.chats; // Сохраняем полученные чаты в глобальную переменную
        renderChatsList(); // Перерисовываем список чатов

    } catch (e) {
        console.error("Ошибка загрузки чатов:", e); // Выводим ошибку в консоль
        chats = []; // Если ошибка — очищаем список чатов
    }
}



// --- Функция переключения состояния сайдбара ---
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const appContainer = document.getElementById('app-container');
    const toggleBtn = document.getElementById('toggle-sidebar-btn');

    if (isSidebarCollapsed) {
        // Развернуть
        sidebar.classList.remove('collapsed');
        appContainer.classList.remove('sidebar-collapsed');
        toggleBtn.textContent = '→';
    } else {
        // Свернуть
        sidebar.classList.add('collapsed');
        appContainer.classList.add('sidebar-collapsed');
        toggleBtn.textContent = '←';
    }

    isSidebarCollapsed = !isSidebarCollapsed;
    localStorage.setItem('sidebarCollapsed', isSidebarCollapsed);
}


// --- *** ИЗМЕНЕНИЕ: Новая функция для отображения имени файла *** ---
function displayFileName() {
    const fileInput = document.getElementById('file-upload');
    const fileNameDisplay = document.getElementById('file-name-display');
    
    if (fileInput.files.length > 0) {
        const file = fileInput.files[0];
        
        // Проверка на .txt
        if (file.name.endsWith('.txt')) {
            currentFile = file;
            fileNameDisplay.textContent = `Файл: ${file.name}`;
        } else {
            alert("Пожалуйста, выберите только .txt файлы.");
            fileInput.value = null; // Сбросить выбор
            currentFile = null;
            fileNameDisplay.textContent = '';
        }
    } else {
        currentFile = null;
        fileNameDisplay.textContent = '';
    }
}

// --- Сброс прикрепленного файла ---
function clearFileInput() {
    document.getElementById('file-upload').value = null;
    document.getElementById('file-name-display').textContent = '';
    currentFile = null;
}


// --- Создание нового чата ---
function createNewChat() {
    // Генерируем уникальный ID для нового чата
    const chatId = crypto.randomUUID ? crypto.randomUUID() : 'chat-' + Date.now();

    // Создаём объект нового чата
    const newChat = {
        id: chatId,
        name: "Новый чат",
        messages: [], // Пустой массив — значит, это локальный чат
    };

    // Добавляем новый чат в начало списка (чтобы он был первым)
    chats.unshift(newChat);

    // Перерисовываем список чатов
    renderChatsList();

    // Устанавливаем этот чат как текущий
    setCurrentChat(chatId);
    
    // *** ИЗМЕНЕНИЕ: Сбрасываем файл при создании нового чата ***
    clearFileInput();
}

// --- Установка текущего чата (загрузка истории) ---
async function setCurrentChat(chatId) {
    if (!chatId) {
        console.error("Попытка установить пустой chatId");
        if (chats.length === 0) {
            createNewChat(); // Если нет чатов — создаём новый
        } else {
            currentChatId = chats[0].id;
            await setCurrentChat(currentChatId); // Повторяем попытку
        }
        return;
    }

    // Если идёт стриминг — не даём переключаться
    if (isStreaming) {
        console.log("🚫 Невозможно переключить чат во время стриминга.");
        return;
    }

    // --- Удаление пустого локального чата ---
    const previousChat = chats.find(c => c.id === currentChatId);
    if (previousChat && previousChat.id !== chatId) {
        // Проверяем, является ли предыдущий чат локальным и пустым
        if (previousChat.messages && previousChat.messages.length === 0) {
            console.log(`🗑️ Удаление пустого локального чата: ${previousChat.name} (ID: ${previousChat.id})`);

            // Удаляем его из массива чатов
            chats = chats.filter(c => c.id !== currentChatId);

            // Перерисовываем список, чтобы он исчез
            renderChatsList();
        }
    }
    // --- Конец удаления ---

    // Если идёт стриминг — отменяем его
    if (isStreaming && activeFetchController) {
        activeFetchController.abort(); // Прерываем запрос
        isStreaming = false;
        activeFetchController = null;
        console.log("⚠️ Активный стриминг отменен из-за смены чата.");
    }

    currentChatId = chatId;
    const chat = chats.find(c => c.id === chatId);
    if (!chat) {
        // Если чат не найден — перезагружаем или выбираем другой
        console.error(`Чат с ID ${chatId} не найден в локальном кэше. Перезагрузка или переключение.`);
        if (chats.length === 0) {
            createNewChat(); // Если всё удалилось — создаём новый
            return;
        }
        // Выбираем первый чат в списке
        await setCurrentChat(chats[0].id);
        return;
    }

    // Очищаем чат в интерфейсе
    const chatDiv = document.getElementById('chat');
    chatDiv.innerHTML = '';
    
    // *** ИЗМЕНЕНИЕ: Сбрасываем файл при переключении чата ***
    clearFileInput();

    // Выделяем текущий чат в списке
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });
    const activeItem = document.querySelector(`.chat-item[data-id="${chatId}"]`);
    if (activeItem) activeItem.classList.add('active');

    // Если чат локальный (есть массив messages), выводим его содержимое
    if (chat.messages) {
        chat.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
        });
        return;
    }

    // --- Если чат уже существует на сервере — загружаем историю ---
    try {
        const response = await fetch('/get_chat_history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, chat_id: chatId })
        });

        if (!response.ok) {
            throw new Error('Не удалось загрузить историю чата');
        }

        const chatHistory = await response.json();

        // Добавляем каждое сообщение в интерфейс
        chatHistory.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
        });

    } catch (error) {
        console.error("Ошибка загрузки истории чата:", error);
        addMessageToChat('ai', `Не удалось загрузить историю: ${error.message}`);
    }
}

// --- Отправка сообщения с использованием стриминга ---
async function sendMessageStream() {
    // Если уже идёт стриминг — не отправляем ещё одно
    if (isStreaming) {
        console.log("🚫 Уже идет стриминг. Подождите или отмените.");
        return;
    }

    const userInput = document.getElementById('userInput');
    const message = userInput.value.trim(); // Получаем текст и убираем пробелы
    
    // *** ИЗМЕНЕНИЕ: Проверяем и сообщение, и файл ***
    if (!message && !currentFile) return; // Не отправляем, если пусто

    // *** ИЗМЕНЕНИЕ: Читаем файл и готовим данные ***
    let fileContent = null;
    let fileName = null;
    let displayMessage = message; // Сообщение для отображения в UI

    if (currentFile) {
        try {
            fileContent = await currentFile.text();
            fileName = currentFile.name;
            
            // Формируем сообщение для UI
            if (displayMessage) {
                displayMessage += `\n\n(Прикреплен файл: ${fileName})`;
            } else {
                displayMessage = `(Прикреплен файл: ${fileName})`;
            }
        } catch (e) {
            console.error("Ошибка чтения файла:", e);
            alert("Не удалось прочитать файл.");
            clearFileInput();
            return;
        }
    }
    
    // Добавляем сообщение пользователя в интерфейс
    addMessageToChat('user', displayMessage);
    userInput.value = '';
    autoResize(); // Подгоняем размер поля ввода
    
    // *** ИЗМЕНЕНИЕ: Сбрасываем файл после подготовки ***
    clearFileInput();

    const currentChat = chats.find(c => c.id === currentChatId);
    if (!currentChat) return;

    // Если это новый локальный чат — сохраняем сообщение локально
    if (currentChat.messages) {
        currentChat.messages.push({
            role: 'user',
            content: displayMessage, // Сохраняем сообщение с припиской
            timestamp: new Date().toISOString()
        });
    }

    // --- Начинаем стриминг ---
    isStreaming = true;
    activeFetchController = new AbortController(); // Создаём контроллер для отмены
    const signal = activeFetchController.signal;

    // Блокируем действия в сайдбаре
    disableSidebarActions(true);

    // Создаём пустое место для ответа ИИ
    const chatDiv = document.getElementById('chat');
    const aiMessageDiv = document.createElement('div');
    aiMessageDiv.className = 'ai-message';

    // Создаём элемент для рендеринга Markdown
    const aiMessageContent = document.createElement('p');
    aiMessageDiv.innerHTML = '<strong>PNI:</strong> ';
    aiMessageDiv.appendChild(aiMessageContent);
    chatDiv.appendChild(aiMessageDiv);

    let fullReply = "";

    try {
        // Отправляем запрос на сервер с сообщением
        const response = await fetch('/send_message_stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // *** ИЗМЕНЕНИЕ: Добавлены file_content и file_name ***
            body: JSON.stringify({
                message: message, // Оригинальное сообщение (без приписки)
                user_id: userId,
                chat_id: currentChatId,
                file_content: fileContent, // Содержимое файла
                file_name: fileName         // Имя файла
            }),
            signal: signal // Передаём сигнал для отмены
        });

        if (!response.ok) {
            const errText = await response.text();
            throw new Error(`Ошибка API (${response.status}): ${errText}`);
        }

        // Читаем ответ по частям (стриминг)
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            fullReply += chunk;

            // Рендерим Markdown на лету
            aiMessageContent.innerHTML = marked.parse(fullReply);

            // Прокручиваем окно вниз
            chatDiv.scrollTop = chatDiv.scrollHeight;
        }

        // Если чат был локальным — удаляем его массив messages, чтобы он загружался с сервера
        if (currentChat.messages) {
            delete currentChat.messages;
        }

    } catch (error) {
        // Проверяем, была ли ошибка отмены
        if (error.name === 'AbortError') {
            console.log("Стриминг успешно отменен.");
            // Удаляем неполный ответ из интерфейса
            if (aiMessageDiv.parentNode === chatDiv) {
                chatDiv.removeChild(aiMessageDiv);
            }
        } else {
            console.error('Ошибка стриминга:', error);
            aiMessageContent.innerHTML = `<strong>Ошибка:</strong> ${error.message}`;
        }

    } finally {
        // --- Завершение стриминга ---
        isStreaming = false;
        activeFetchController = null;

        // Разблокируем действия в сайдбаре
        disableSidebarActions(false);

        // Обновляем список чатов
        await loadChats();

        // Повторно выделяем активный чат
        const activeItem = document.querySelector(`.chat-item[data-id="${currentChatId}"]`);
        if (activeItem) activeItem.classList.add('active');
    }
}

// --- Рендер списка чатов ---
function renderChatsList() {
    const list = document.getElementById('chats-list');
    list.innerHTML = '';

    // Блокируем действия, если идёт стриминг
    if (isStreaming) {
        list.classList.add('disabled-actions');
    } else {
        list.classList.remove('disabled-actions');
    }

    const search = document.getElementById('search-chats').value.toLowerCase();
    const filteredChats = chats.filter(chat =>
        chat.name.toLowerCase().includes(search)
    );

    filteredChats.forEach(chat => {
        const item = document.createElement('div');
        item.className = 'chat-item';
        item.dataset.id = chat.id;
        if (chat.id === currentChatId) item.classList.add('active');

        // Получаем последнее сообщение для отображения в списке
        let lastText;
        if (chat.preview) {
            lastText = chat.preview.length > 30 ? chat.preview.substring(0, 30) + '...' : chat.preview;
        } else if (chat.messages && chat.messages.length > 0) {
            const lastMsg = chat.messages[chat.messages.length - 1];
            lastText = lastMsg.content.length > 30 ? lastMsg.content.substring(0, 30) + '...' : lastMsg.content;
        } else {
            lastText = 'Пустой чат';
        }

        // Формируем HTML для чата
        item.innerHTML = `
            <span class="avatar">💬</span>
            <div class="chat-info">
                <div class="chat-name">${chat.name}</div>
                <div class="chat-preview">${lastText}</div>
            </div>
            <span class="delete-chat-btn" title="Удалить чат">🗑️</span>
        `;

        // Клик по чату — переключение
        item.addEventListener('click', () => {
            setCurrentChat(chat.id);
        });

        // Клик по кнопке удаления
        const deleteBtn = item.querySelector('.delete-chat-btn');
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteChat(chat.id, chat.name);
        });

        list.appendChild(item);
    });
}

// --- Удаление чата ---
async function deleteChat(chatId, chatName) {
    // Не даём удалять, если идёт стриминг
    if (isStreaming) {
        alert("Нельзя удалить чат во время генерации ответа.");
        return;
    }

    // Подтверждение удаления
    if (!confirm(`Вы уверены, что хотите удалить чат "${chatName}"?`)) {
        return;
    }

    try {
        const response = await fetch('/delete_chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, chat_id: chatId })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Не удалось удалить чат');
        }

        // Удаляем чат из локального массива
        chats = chats.filter(c => c.id !== chatId);

        // Если удаляли текущий чат — переключаемся на другой
        if (currentChatId === chatId) {
            // Очищаем интерфейс
            document.getElementById('chat').innerHTML = '';

            // Если есть другие чаты — переключаемся на первый
            if (chats.length > 0) {
                await setCurrentChat(chats[0].id);
            } else {
                // Если чатов нет — создаём new
                createNewChat();
            }
        }
        renderChatsList(); // Перерисовываем список

    } catch (error) {
        console.error("Ошибка удаления чата:", error);
        alert(`Ошибка: ${error.message}`);
    }
}

// --- Поиск чатов ---
function filterChats() {
    renderChatsList(); // Перерисовываем список с учётом поиска
}

// --- Авто-растягивание поля ввода ---
function autoResize() {
    const userInput = document.getElementById('userInput');
    userInput.style.height = 'auto'; // Сбрасываем высоту
    const maxHeight = 300;
    userInput.style.height = Math.min(userInput.scrollHeight, maxHeight) + 'px'; // Подгоняем под содержимое
}

// --- Добавление сообщения в чат ---
function addMessageToChat(role, content) {
    const chatDiv = document.getElementById('chat');
    const messageDiv = document.createElement('div');
    messageDiv.className = role === 'user' ? 'user-message' : 'ai-message';

    if (role === 'user') {
        // Для сообщений пользователя — просто текст
        const textNode = document.createTextNode(content);
        const p = document.createElement('p');
        p.appendChild(textNode);
        p.innerHTML = p.innerHTML.replace(/\n/g, '<br>'); // Перенос строк

        const strong = document.createElement('strong');
        strong.textContent = "Вы: ";

        messageDiv.appendChild(strong);
        messageDiv.appendChild(p);

    } else {
        // Для ответов ИИ — используем Markdown
        const htmlContent = marked.parse(content);
        messageDiv.innerHTML = `<strong>PNI:</strong> ${htmlContent}`;
    }

    chatDiv.appendChild(messageDiv);
    chatDiv.scrollTop = chatDiv.scrollHeight; // Прокручиваем вниз
}

// --- Блокировка/разблокировка действий в сайдбаре ---
function disableSidebarActions(disable) {
    const list = document.getElementById('chats-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    const newChatBtnElement = document.getElementById('new-chat-btn');
    
    // *** ИЗМЕНЕНИЕ: 'personalitySelector' удален ***

    if (disable) {
        list.classList.add('disabled-actions');
        newChatBtn.disabled = true;
        // Блокируем кнопку создания нового чата
        newChatBtnElement.onclick = () => { console.log("🚫 Действие заблокировано во время стриминга."); };
    } else {
        list.classList.remove('disabled-actions');
        newChatBtn.disabled = false;
        // Восстанавливаем оригинальную функцию кнопки
        newChatBtnElement.onclick = createNewChat;
    }
}

// --- Переключение модели (на будущее) ---
function switchModel(modelName) {
    console.log("Выбрана модель:", modelName);
    localStorage.setItem('selected_model', modelName);
}

// --- Обработчики событий ---
const userInput = document.getElementById('userInput');
userInput.addEventListener('input', autoResize); // Авто-растягивание при вводе
userInput.addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessageStream(); // Отправка по Enter
    }
});

// *** ИЗМЕНЕНИЕ: Обработчик 'personalitySelector' удален ***


// --- Инициализация состояния сайдбара из localStorage ---
document.addEventListener('DOMContentLoaded', () => {
    const savedState = localStorage.getItem('sidebarCollapsed');
    if (savedState === 'true') {
        isSidebarCollapsed = true;
        document.getElementById('sidebar').classList.add('collapsed');
        document.getElementById('app-container').classList.add('sidebar-collapsed');
        document.getElementById('toggle-sidebar-btn').textContent = '←';
    }
});

// --- Обработчик клика по кнопке сворачивания ---
document.getElementById('toggle-sidebar-btn').addEventListener('click', toggleSidebar);