// --- Глобальные переменные ---
let currentChatId = null; // ID текущего чата
let chats = []; // Массив всех чатов
let userId = localStorage.getItem('chat_user_id'); // ID пользователя из локального хранилища
let isSidebarCollapsed = false;
let currentFile = null; // *** ИЗМЕНЕНИЕ: Хранит выбранный файл ***

// *** НОВЫЕ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ АВТОРИЗАЦИИ ***
let isAuthenticated = false; // Флаг авторизации
let currentUserNickname = "WIP"; // Текущий никнейм

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

// --- Функция для установки состояния авторизации ---
function setAuthState(authenticated, nickname = "WIP") {
    isAuthenticated = authenticated;
    currentUserNickname = nickname;

    const userMenuBtn = document.getElementById('user-menu-btn');
    const userAvatar = document.getElementById('user-avatar');
    const userNickname = document.getElementById('user-nickname');
    const logoutIcon = document.getElementById('logout-icon');

    if (authenticated) {
        userMenuBtn.classList.add('authenticated');
        userNickname.textContent = nickname;
        if (nickname && nickname.length > 0) {
            userAvatar.textContent = nickname.charAt(0).toUpperCase();
        }
    } else {
        userMenuBtn.classList.remove('authenticated');
        userNickname.textContent = "WIP";
        userAvatar.textContent = "A"; // По умолчанию
    }
}

// --- Функция для открытия окна авторизации ---
function openAuthModal() {
    document.getElementById('auth-modal').style.display = 'flex';
    document.getElementById('login-input').focus();
}

// --- Функция для закрытия окна авторизации ---
function closeAuthModal() {
    document.getElementById('auth-modal').style.display = 'none';
    document.getElementById('login-form').reset();
}

// --- Функция для открытия окна подтверждения выхода ---
function openLogoutModal() {
    document.getElementById('logout-modal').style.display = 'flex';
}

// --- Функция для закрытия окна подтверждения выхода ---
function closeLogoutModal() {
    document.getElementById('logout-modal').style.display = 'none';
}

// --- Функция для выхода из системы ---
function logout() {
    localStorage.removeItem('isAuthenticated');
    localStorage.removeItem('currentUserNickname');
    setAuthState(false, "WIP");
    console.log("Пользователь вышел.");
}

// --- Инициализация приложения ---
document.addEventListener('DOMContentLoaded', async () => {
    // 1. Загружаем список чатов с сервера
    await loadChats();

    // 2. Выбираем самый новый чат или создаём новый
    if (chats.length > 0) {
        await setCurrentChat(chats[0].id); // Устанавливаем первый чат
    } else {
        createNewChat(); // Если чатов нет — создаём новый
    }

    // --- Инициализация состояния авторизации из localStorage ---
    const savedIsAuthenticated = localStorage.getItem('isAuthenticated') === 'true';
    const savedNickname = localStorage.getItem('currentUserNickname') || "WIP";
    setAuthState(savedIsAuthenticated, savedNickname);
});

// --- Загрузка списка чатов с сервера ---
async function loadChats() {
    try {
        const response = await fetch('/get_chats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });

        if (!response.ok) {
            throw new Error('Не удалось загрузить чаты');
        }

        const data = await response.json();
        chats = data.chats;
        renderChatsList();

    } catch (e) {
        console.error("Ошибка загрузки чатов:", e);
        chats = [];
    }
}

// --- Функция переключения состояния сайдбара ---
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const appContainer = document.getElementById('app-container');
    const toggleBtn = document.getElementById('toggle-sidebar-btn');

    if (isSidebarCollapsed) {
        sidebar.classList.remove('collapsed');
        appContainer.classList.remove('sidebar-collapsed');
        toggleBtn.textContent = '→';
    } else {
        sidebar.classList.add('collapsed');
        appContainer.classList.add('sidebar-collapsed');
        toggleBtn.textContent = '←';
    }

    isSidebarCollapsed = !isSidebarCollapsed;
    localStorage.setItem('sidebarCollapsed', isSidebarCollapsed);
}

// --- *** ИЗМЕНЕНИЕ: Функция для отображения имени файла *** ---
function displayFileName() {
    const fileInput = document.getElementById('file-upload');
    const fileNameDisplay = document.getElementById('file-name-display');

    if (fileInput.files.length > 0) {
        const file = fileInput.files[0];
        // --- УБРАНА ВАЛИДАЦИЯ .txt ---
        currentFile = file;
        fileNameDisplay.textContent = `Файл: ${file.name}`;
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
    const chatId = crypto.randomUUID ? crypto.randomUUID() : 'chat-' + Date.now();
    const newChat = {
        id: chatId,
        name: "Новый чат",
        messages: [],
    };
    chats.unshift(newChat);
    renderChatsList();
    setCurrentChat(chatId);
    clearFileInput();
}

// --- Установка текущего чата (загрузка истории) ---
async function setCurrentChat(chatId) {
    if (!chatId) {
        console.error("Попытка установить пустой chatId");
        if (chats.length === 0) {
            createNewChat();
        } else {
            currentChatId = chats[0].id;
            await setCurrentChat(currentChatId);
        }
        return;
    }

    if (isStreaming) {
        console.log("🚫 Невозможно переключить чат во время стриминга.");
        return;
    }

    const previousChat = chats.find(c => c.id === currentChatId);
    if (previousChat && previousChat.id !== chatId) {
        if (previousChat.messages && previousChat.messages.length === 0) {
            console.log(`🗑️ Удаление пустого локального чата: ${previousChat.name} (ID: ${previousChat.id})`);
            chats = chats.filter(c => c.id !== currentChatId);
            renderChatsList();
        }
    }

    if (isStreaming && activeFetchController) {
        activeFetchController.abort();
        isStreaming = false;
        activeFetchController = null;
        console.log("⚠️ Активный стриминг отменен из-за смены чата.");
    }

    currentChatId = chatId;
    const chat = chats.find(c => c.id === chatId);
    if (!chat) {
        console.error(`Чат с ID ${chatId} не найден в локальном кэше.`);
        if (chats.length === 0) {
            createNewChat();
            return;
        }
        await setCurrentChat(chats[0].id);
        return;
    }

    const chatDiv = document.getElementById('chat');
    chatDiv.innerHTML = '';
    clearFileInput();

    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });
    const activeItem = document.querySelector(`.chat-item[data-id="${chatId}"]`);
    if (activeItem) activeItem.classList.add('active');

    if (chat.messages) {
        chat.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
        });
        return;
    }

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
        chatHistory.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
        });

    } catch (error) {
        console.error("Ошибка загрузки истории чата:", error);
        addMessageToChat('ai', `Не удалось загрузить историю: ${error.message}`);
    }
}

// --- *** ИЗМЕНЕНИЕ: Отправка сообщения (переход на FormData) *** ---
async function sendMessageStream() {
    if (isStreaming) {
        console.log("🚫 Уже идет стриминг. Подождите или отмените.");
        return;
    }

    const userInput = document.getElementById('userInput');
    const message = userInput.value.trim();
    if (!message && !currentFile) return;

    let fileName = null;
    let displayMessage = message;

    if (currentFile) {
        fileName = currentFile.name;
        if (displayMessage) {
            displayMessage += `\n\n(Прикреплен файл: ${fileName})`;
        } else {
            displayMessage = `(Прикреплен файл: ${fileName})`;
        }
    }

    addMessageToChat('user', displayMessage);
    userInput.value = '';
    autoResize();
    // Файл очистим *после* отправки

    const currentChat = chats.find(c => c.id === currentChatId);
    if (!currentChat) return;

    if (currentChat.messages) {
        currentChat.messages.push({
            role: 'user',
            content: displayMessage,
            timestamp: new Date().toISOString()
        });
    }

    isStreaming = true;
    activeFetchController = new AbortController();
    const signal = activeFetchController.signal;
    disableSidebarActions(true);

    const chatDiv = document.getElementById('chat');
    const aiMessageDiv = document.createElement('div');
    aiMessageDiv.className = 'ai-message';
    const aiMessageContent = document.createElement('p');
    aiMessageDiv.innerHTML = '<strong>PNI:</strong> ';
    aiMessageDiv.appendChild(aiMessageContent);
    chatDiv.appendChild(aiMessageDiv);

    let fullReply = "";

    try {
        // *** ИЗМЕНЕНИЕ: Создаем FormData вместо JSON ***
        const formData = new FormData();
        formData.append('message', message);
        formData.append('user_id', userId);
        formData.append('chat_id', currentChatId);
        
        if (currentFile) {
            formData.append('file', currentFile); // Отправляем сам файл
        }
        
        clearFileInput(); // Очищаем файл *после* добавления в FormData

        // *** ИЗМЕНЕНИЕ: Отправляем FormData. Убираем 'Content-Type' (браузер добавит сам) ***
        const response = await fetch('/send_message_stream', {
            method: 'POST',
            // headers: { 'Content-Type': 'application/json' }, // <-- УБРАЛИ
            body: formData, // <-- Используем FormData
            signal: signal
        });

        if (!response.ok) {
            const errText = await response.text();
            throw new Error(`Ошибка API (${response.status}): ${errText}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            fullReply += chunk;
            aiMessageContent.innerHTML = marked.parse(fullReply);
            chatDiv.scrollTop = chatDiv.scrollHeight;
        }

        if (currentChat.messages) {
            delete currentChat.messages;
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            console.log("Стриминг успешно отменен.");
            if (aiMessageDiv.parentNode === chatDiv) {
                chatDiv.removeChild(aiMessageDiv);
            }
        } else {
            console.error('Ошибка стриминга:', error);
            aiMessageContent.innerHTML = `<strong>Ошибка:</strong> ${error.message}`;
        }

    } finally {
        isStreaming = false;
        activeFetchController = null;
        disableSidebarActions(false);
        await loadChats();
        const activeItem = document.querySelector(`.chat-item[data-id="${currentChatId}"]`);
        if (activeItem) activeItem.classList.add('active');
    }
}
// --- *** КОНЕЦ ИЗМЕНЕНИЯ *** ---

// --- Рендер списка чатов ---
function renderChatsList() {
    const list = document.getElementById('chats-list');
    list.innerHTML = '';

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

        let lastText;
        if (chat.preview) {
            lastText = chat.preview.length > 30 ? chat.preview.substring(0, 30) + '...' : chat.preview;
        } else if (chat.messages && chat.messages.length > 0) {
            const lastMsg = chat.messages[chat.messages.length - 1];
            lastText = lastMsg.content.length > 30 ? lastMsg.content.substring(0, 30) + '...' : lastMsg.content;
        } else {
            lastText = 'Пустой чат';
        }

        item.innerHTML = `
            <span class="avatar">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                </svg>
            </span>
            <div class="chat-info">
                <div class="chat-name">${chat.name}</div>
                <div class="chat-preview">${lastText}</div>
            </div>
            <span class="delete-chat-btn" title="Удалить чат">🗑️</span>
        `;

        item.addEventListener('click', () => {
            setCurrentChat(chat.id);
        });

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
    if (isStreaming) {
        alert("Нельзя удалить чат во время генерации ответа.");
        return;
    }

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

        chats = chats.filter(c => c.id !== chatId);

        if (currentChatId === chatId) {
            document.getElementById('chat').innerHTML = '';
            if (chats.length > 0) {
                await setCurrentChat(chats[0].id);
            } else {
                createNewChat();
            }
        }
        renderChatsList();

    } catch (error) {
        console.error("Ошибка удаления чата:", error);
        alert(`Ошибка: ${error.message}`);
    }
}

// --- Поиск чатов ---
function filterChats() {
    renderChatsList();
}

// --- Авто-растягивание поля ввода ---
function autoResize() {
    const userInput = document.getElementById('userInput');
    userInput.style.height = 'auto';
    const maxHeight = 300;
    userInput.style.height = Math.min(userInput.scrollHeight, maxHeight) + 'px';
}

// --- Добавление сообщения в чат ---
function addMessageToChat(role, content) {
    const chatDiv = document.getElementById('chat');
    const messageDiv = document.createElement('div');
    messageDiv.className = role === 'user' ? 'user-message' : 'ai-message';

    if (role === 'user') {
        const textNode = document.createTextNode(content);
        const p = document.createElement('p');
        p.appendChild(textNode);
        p.innerHTML = p.innerHTML.replace(/\n/g, '<br>');
        const strong = document.createElement('strong');
        strong.textContent = "Вы: ";
        messageDiv.appendChild(strong);
        messageDiv.appendChild(p);
    } else {
        const htmlContent = marked.parse(content);
        messageDiv.innerHTML = `<strong>PNI:</strong> ${htmlContent}`;
    }

    chatDiv.appendChild(messageDiv);
    chatDiv.scrollTop = chatDiv.scrollHeight;
}

// --- Блокировка/разблокировка действий в сайдбаре ---
function disableSidebarActions(disable) {
    const list = document.getElementById('chats-list');
    const newChatBtn = document.getElementById('new-chat-btn');

    if (disable) {
        list.classList.add('disabled-actions');
        newChatBtn.disabled = true;
        newChatBtn.onclick = () => { console.log("🚫 Действие заблокировано во время стриминга."); };
    } else {
        list.classList.remove('disabled-actions');
        newChatBtn.disabled = false;
        newChatBtn.onclick = createNewChat;
    }
}

// --- Переключение модели (на будущее) ---
function switchModel(modelName) {
    console.log("Выбрана модель:", modelName);
    localStorage.setItem('selected_model', modelName);
}

// --- Обработчики событий ---
const userInput = document.getElementById('userInput');
userInput.addEventListener('input', autoResize);
userInput.addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessageStream();
    }
});

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

// --- НОВЫЕ ОБРАБОТЧИКИ ДЛЯ АВТОРИЗАЦИИ ---

// Обработчик клика по кнопке пользователя в footer
document.addEventListener('click', function (e) {
    // Используем делегирование, чтобы убедиться, что элементы уже существуют
    if (e.target.closest('#user-menu-btn')) {
        e.stopPropagation();
        if (isAuthenticated) {
            openLogoutModal();
        } else {
            openAuthModal();
        }
    }
});

// Обработчик отправки формы входа
document.addEventListener('submit', function (e) {
    if (e.target.id === 'login-form') {
        e.preventDefault();
        const login = document.getElementById('login-input').value.trim();
        const password = document.getElementById('password-input').value.trim();

        // Имитация успешного входа (замените на реальный запрос к API)
        if (login && password) {
            setAuthState(true, login);
            localStorage.setItem('isAuthenticated', 'true');
            localStorage.setItem('currentUserNickname', login);
            closeAuthModal();
            console.log(`Пользователь ${login} вошел.`);
        } else {
            alert("Пожалуйста, заполните все поля.");
        }
    }
});

// Обработчики для ссылок внутри окна авторизации
document.addEventListener('click', function (e) {
    if (e.target.id === 'forgot-password') {
        e.preventDefault();
        alert("Функция восстановления пароля пока не реализована.");
    } else if (e.target.id === 'register-link') {
        e.preventDefault();
        alert("Функция регистрации пока не реализована.");
    }
});

// Обработчики для окна выхода
document.addEventListener('click', function (e) {
    if (e.target.id === 'confirm-logout') {
        logout();
        closeLogoutModal();
    } else if (e.target.id === 'cancel-logout') {
        closeLogoutModal();
    }
});

// Обработчик клика по фону модального окна
window.addEventListener('click', function (event) {
    const authModal = document.getElementById('auth-modal');
    const logoutModal = document.getElementById('logout-modal');
    if (event.target === authModal) {
        closeAuthModal();
    }
    if (event.target === logoutModal) {
        closeLogoutModal();
    }
});