// --- Глобальные переменные ---
let currentChatId = null; // ID текущего чата
let chats = []; // Массив всех чатов
// *** ИЗМЕНЕНИЕ: userId и isAuthenticated УДАЛЕНЫ ***
// let userId = localStorage.getItem('chat_user_id'); // <-- УДАЛЕНО
// let isAuthenticated = false; // <-- УДАЛЕНО
let isSidebarCollapsed = false;
let currentFile = null;

// *** ИЗМЕНЕНИЕ: currentUserNickname теперь берется из localStorage ***
// let currentUserNickname = "WIP"; // <-- УДАЛЕНО

// --- Переменные для управления стримингом ---
let isStreaming = false; // Флаг, показывающий, идёт ли сейчас стриминг ответа
let activeFetchController = null; // Контроллер для отмены запроса, если нужно

// *** ИЗМЕНЕНИЕ: Глобальная переменная userId УДАЛЕНА ***
// (Старая логика генерации ID удалена)

// --- *** НОВАЯ ФУНКЦИЯ: Хэширование пароля (SHA-256) *** ---
// (Без изменений)
async function hashPassword(password) {
    const encoder = new TextEncoder();
    const data = encoder.encode(password);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    return hashHex;
}

// *** ИЗМЕНЕНИЕ: Новые функции для управления состоянием аутентификации ***
function getToken() {
    return localStorage.getItem('access_token');
}

function getNickname() {
    return localStorage.getItem('currentUserNickname');
}

function storeCredentials(token, nickname) {
    localStorage.setItem('access_token', token);
    localStorage.setItem('currentUserNickname', nickname);
    updateUIForAuthState();
}

function clearCredentials() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('currentUserNickname');
    updateUIForAuthState();
}

// --- Функция для установки состояния авторизации (обновление UI) ---
function updateUIForAuthState() {
    const token = getToken();
    const nickname = getNickname();
    const isAuthenticated = !!token; // Авторизован, если есть токен

    const userMenuBtn = document.getElementById('user-menu-btn');
    const userAvatar = document.getElementById('user-avatar');
    const userNickname = document.getElementById('user-nickname');

    if (isAuthenticated && nickname) {
        userMenuBtn.classList.add('authenticated');
        userNickname.textContent = nickname;
        userAvatar.textContent = nickname.charAt(0).toUpperCase();
    } else {
        userMenuBtn.classList.remove('authenticated');
        userNickname.textContent = "WIP"; // Будет скрыто модальным окном
        userAvatar.textContent = "A"; // По умолчанию
    }

    // Обновляем мобильную версию
    updateMobileAuthState();
}

// --- Функция для открытия окна авторизации ---
function openAuthModal() {
    const authModal = document.getElementById('auth-modal');
    authModal.style.display = 'flex';
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
    // *** ИЗМЕНЕНИЕ: Очищаем токен и никнейм ***
    clearCredentials();
    console.log("Пользователь вышел.");

    // Очищаем чаты
    chats = [];
    renderChatsList();
    document.getElementById('chat').innerHTML = '';
    document.getElementById('chat-mobile').innerHTML = '';

    // Показать обязательное окно входа
    const authModal = document.getElementById('auth-modal');
    authModal.style.display = 'flex';
    authModal.classList.add('mandatory');
    document.getElementById('login-input').focus();
}

// --- Инициализация приложения ---
document.addEventListener('DOMContentLoaded', async () => {
    
    // --- Инициализация состояния авторизации из localStorage ---
    updateUIForAuthState();
    const token = getToken();
    
    if (token) {
        // Пользователь (вероятно) авторизован
        console.log("Найден токен, загрузка чатов...");
        await loadChats();

        // Выбираем самый новый чат или создаём новый
        if (chats.length > 0) {
            await setCurrentChat(chats[0].id);
        } else {
            createNewChat();
        }
    } else {
        // Пользователь не авторизован
        console.log("Токен не найден, отображение окна входа.");
        setAuthState(false);
        openAuthModal();
        document.getElementById('auth-modal').classList.add('mandatory');
    }
    // --- КОНЕЦ ИЗМЕНЕНИЯ ---


    // --- (Остальная часть DOMContentLoaded без изменений) ---
    const savedState = localStorage.getItem('sidebarCollapsed');
    if (savedState === 'true') {
        isSidebarCollapsed = true;
        document.getElementById('sidebar').classList.add('collapsed');
        document.getElementById('app-container').classList.add('sidebar-collapsed');
        document.getElementById('toggle-sidebar-btn').textContent = '←';
    }
    const hamburgerBtn = document.getElementById('hamburger-menu-btn');
    if (hamburgerBtn) {
        hamburgerBtn.addEventListener('click', toggleMobileSidebar);
    }
    const userInputMobile = document.getElementById('userInput-mobile');
    if (userInputMobile) {
        userInputMobile.addEventListener('input', autoResizeMobile);
        userInputMobile.addEventListener('keypress', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessageStreamMobile();
            }
        });
    }
    document.addEventListener('click', function (e) {
        if (e.target.closest('#user-menu-btn-mobile')) {
            e.stopPropagation();
            if (getToken()) { // Проверяем токен
                openLogoutModal();
            } else {
                openAuthModal();
                document.getElementById('auth-modal').classList.add('mandatory');
            }
        }
    });
    const searchInputMobile = document.getElementById('search-chats-mobile');
    if (searchInputMobile) {
        searchInputMobile.addEventListener('input', filterChatsMobile);
    }
    const newChatBtnMobile = document.getElementById('new-chat-btn-mobile');
    if (newChatBtnMobile) {
        newChatBtnMobile.onclick = createNewChat;
    }
    updateMobileChatsList();
    updateMobileAuthState(); // Дублирующий вызов, но безопасный
});

// --- Загрузка списка чатов с сервера ---
async function loadChats() {
    const token = getToken();
    if (!token) {
        console.log("Пользователь не авторизован, загрузка чатов отложена.");
        chats = [];
        renderChatsList();
        return;
    }
    
    try {
        // *** ИЗМЕНЕНИЕ: Отправляем токен в заголовке, метод GET, без тела ***
        const response = await fetch('/get_chats', {
            method: 'GET',
            headers: { 
                'Authorization': 'Bearer ' + token
            }
        });

        if (response.status === 401) {
            // Токен истек или невалиден
            console.error("Токен недействителен. Требуется повторный вход.");
            logout(); // Разлогиниваем пользователя
            return;
        }
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
// (Без изменений)
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

// --- Функция для отображения имени файла ---
// (Без изменений)
function displayFileName() {
    const fileInput = document.getElementById('file-upload');
    const fileNameDisplay = document.getElementById('file-name-display');

    if (fileInput.files.length > 0) {
        const file = fileInput.files[0];
        currentFile = file;
        fileNameDisplay.textContent = `Файл: ${file.name}`;
    } else {
        currentFile = null;
        fileNameDisplay.textContent = '';
    }
}

// --- Сброс прикрепленного файла ---
// (Без изменений)
function clearFileInput() {
    document.getElementById('file-upload').value = null;
    document.getElementById('file-name-display').textContent = '';
    currentFile = null;
}

// --- Создание нового чата ---
function createNewChat() {
    // *** ИЗМЕНЕНИЕ: Проверяем по токену ***
    if (!getToken()) {
        openAuthModal();
        document.getElementById('auth-modal').classList.add('mandatory');
        return;
    }
    
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

    // (Логика очистки пустого чата без изменений)
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

    // Если чат новый (messages: []), не делаем запрос
    if (chat.messages && chat.messages.length > 0) {
        chat.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
        });
        // Обновляем мобильную версию
        const chatDivMobile = document.getElementById('chat-mobile');
        chatDivMobile.innerHTML = '';
        chat.messages.forEach(msg => {
            addMessageToChatMobile(msg.role, msg.content);
        });
        return;
    }
    
    // Если у чата нет 'messages', значит он с сервера и мы загружаем историю
    // (кроме случая chat.messages = [], это новый пустой чат)
    if (chat.messages) { // chat.messages === []
         // Очищаем мобильный чат для нового пустого чата
        const chatDivMobile = document.getElementById('chat-mobile');
        chatDivMobile.innerHTML = '';
        return;
    }

    const token = getToken();
    if (!token) {
        logout(); // Если нет токена, разлогинить
        return;
    }

    try {
        // *** ИЗМЕНЕНИЕ: Отправляем токен и chat_id ***
        const response = await fetch('/get_chat_history', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token 
            },
            body: JSON.stringify({ chat_id: chatId })
        });

        if (response.status === 401) {
            logout();
            return;
        }
        if (!response.ok) {
            throw new Error('Не удалось загрузить историю чата');
        }

        const chatHistory = await response.json();
        chatHistory.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
        });
        // Обновляем мобильную версию
        const chatDivMobile = document.getElementById('chat-mobile');
        chatDivMobile.innerHTML = '';
        chatHistory.messages.forEach(msg => {
            addMessageToChatMobile(msg.role, msg.content);
        });

    } catch (error) {
        console.error("Ошибка загрузки истории чата:", error);
        addMessageToChat('ai', `Не удалось загрузить историю: ${error.message}`);
        addMessageToChatMobile('ai', `Не удалось загрузить историю: ${error.message}`);
    }
}

// --- Отправка сообщения ---
async function sendMessageStream() {
    if (isStreaming) {
        console.log("🚫 Уже идет стриминг. Подождите или отмените.");
        return;
    }
    
    const token = getToken();
    if (!token) {
        logout(); // Разлогинить, если нет токена
        return;
    }

    const userInput = document.getElementById('userInput');
    const message = userInput.value.trim();
    if (!message && !currentFile) return;

    // (Логика displayMessage без изменений)
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
        const formData = new FormData();
        formData.append('message', message);
        // *** ИЗМЕНЕНИЕ: user_id УДАЛЕН ***
        // formData.append('user_id', userId); // <-- УДАЛЕНО
        formData.append('chat_id', currentChatId);
        if (currentFile) {
            formData.append('file', currentFile);
        }
        clearFileInput();

        // *** ИЗМЕНЕНИЕ: Добавляем 'Authorization' header ***
        const response = await fetch('/send_message_stream', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + token
            },
            body: formData,
            signal: signal
        });
        
        if (response.status === 401) {
            logout(); // Токен истек
            throw new Error("Сессия истекла. Пожалуйста, войдите заново.");
        }
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

        // Если это был новый чат, удаляем 'messages'
        // чтобы при следующем выборе он загрузился с сервера
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
        // Обновляем список чатов (чтобы обновить превью)
        await loadChats(); 
        // Снова выделяем активный чат
        const activeItem = document.querySelector(`.chat-item[data-id="${currentChatId}"]`);
        if (activeItem) activeItem.classList.add('active');
    }
}

// --- Рендер списка чатов ---
// (Без изменений)
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
    updateMobileChatsList();
}

// --- Удаление чата ---
async function deleteChat(chatId, chatName) {
    if (isStreaming) {
        alert("Нельзя удалить чат во время генерации ответа.");
        return;
    }

    const token = getToken();
    if (!token) {
        logout();
        return;
    }

    if (!confirm(`Вы уверены, что хотите удалить чат "${chatName}"?`)) {
        return;
    }

    try {
        // *** ИЗМЕНЕНИЕ: Отправляем токен и chat_id ***
        const response = await fetch('/delete_chat', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify({ chat_id: chatId })
        });

        if (response.status === 401) {
            logout();
            return;
        }
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Не удалось удалить чат');
        }

        chats = chats.filter(c => c.id !== chatId);

        if (currentChatId === chatId) {
            document.getElementById('chat').innerHTML = '';
            document.getElementById('chat-mobile').innerHTML = '';
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
// (Без изменений)
function filterChats() {
    renderChatsList();
}

// --- Авто-растягивание поля ввода ---
// (Без изменений)
function autoResize() {
    const userInput = document.getElementById('userInput');
    userInput.style.height = 'auto';
    const maxHeight = 300;
    userInput.style.height = Math.min(userInput.scrollHeight, maxHeight) + 'px';
}

// --- Добавление сообщения в чат ---
// (Без изменений)
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
// (Без изменений)
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
// (Без изменений)
function switchModel(modelName) {
    console.log("Выбрана модель:", modelName);
    localStorage.setItem('selected_model', modelName);
}

// --- Функция для открытия окна регистрации ---
// (Без изменений)
function openRegisterModal() {
    document.getElementById('auth-modal').style.display = 'none';
    document.getElementById('register-modal').style.display = 'flex';
    document.getElementById('register-login').focus();
}

// --- Функция для закрытия окна регистрации ---
// (Без изменений)
function closeRegisterModal() {
    document.getElementById('register-modal').style.display = 'none';
    document.getElementById('register-form').reset();
}


// --- *** ФУНКЦИИ ДЛЯ СИНХРОНИЗАЦИИ ПК И МОБИЛЬНОЙ ВЕРСИЙ *** ---
// (Логика рендеринга без изменений, но вызовы API внутри них
//  теперь будут использовать обновленные `sendMessageStreamMobile` и `deleteChatMobile`)

// Функция для обновления мобильного списка чатов
function updateMobileChatsList() {
    // (Без изменений)
    const mobileList = document.getElementById('chats-list-mobile');
    if (!mobileList) return;
    mobileList.innerHTML = '';
    if (isStreaming) {
        mobileList.classList.add('disabled-actions');
    } else {
        mobileList.classList.remove('disabled-actions');
    }
    const search = document.getElementById('search-chats-mobile').value.toLowerCase();
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
            toggleMobileSidebar();
        });
        const deleteBtn = item.querySelector('.delete-chat-btn');
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteChatMobile(chat.id, chat.name);
        });
        mobileList.appendChild(item);
    });
}

// Функция для обновления состояния авторизации в мобильной версии
function updateMobileAuthState() {
    // *** ИЗМЕНЕНИЕ: Логика на основе getNickname() ***
    const nickname = getNickname();
    const isAuthenticated = !!nickname;

    const userMenuBtnMobile = document.getElementById('user-menu-btn-mobile');
    const userAvatarMobile = document.getElementById('user-avatar-mobile');
    const userNicknameMobile = document.getElementById('user-nickname-mobile');

    if (isAuthenticated) {
        userMenuBtnMobile.classList.add('authenticated');
        userNicknameMobile.textContent = nickname;
        userAvatarMobile.textContent = nickname.charAt(0).toUpperCase();
    } else {
        userMenuBtnMobile.classList.remove('authenticated');
        userNicknameMobile.textContent = "WIP";
        userAvatarMobile.textContent = "A";
    }
}

// Функция для переключения мобильного сайдбара
// (Без изменений)
function toggleMobileSidebar() {
    const sidebar = document.getElementById('sidebar-mobile');
    sidebar.classList.toggle('open');
}

// Функция для отправки сообщения из мобильной версии
async function sendMessageStreamMobile() {
    if (isStreaming) {
        console.log("🚫 Уже идет стриминг. Подождите или отмените.");
        return;
    }
    
    // *** ИЗМЕНЕНИЕ: Проверка токена ***
    const token = getToken();
    if (!token) {
        logout();
        return;
    }

    const userInput = document.getElementById('userInput-mobile');
    const message = userInput.value.trim();
    if (!message && !currentFile) return;

    // (Логика displayMessage без изменений)
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

    addMessageToChatMobile('user', displayMessage);
    userInput.value = '';
    autoResizeMobile();

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
    disableSidebarActions(true); // Блокирует и ПК, и мобильный

    const chatDiv = document.getElementById('chat-mobile');
    const aiMessageDiv = document.createElement('div');
    aiMessageDiv.className = 'ai-message';
    const aiMessageContent = document.createElement('p');
    aiMessageDiv.innerHTML = '<strong>PNI:</strong> ';
    aiMessageDiv.appendChild(aiMessageContent);
    chatDiv.appendChild(aiMessageDiv);

    let fullReply = "";
    try {
        const formData = new FormData();
        formData.append('message', message);
        // *** ИЗМЕНЕНИЕ: user_id УДАЛЕН ***
        // formData.append('user_id', userId); // <-- УДАЛЕНО
        formData.append('chat_id', currentChatId);
        if (currentFile) {
            formData.append('file', currentFile);
        }
        clearFileInputMobile();

        // *** ИЗМЕНЕНИЕ: Добавляем 'Authorization' header ***
        const response = await fetch('/send_message_stream', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + token
            },
            body: formData,
            signal: signal
        });

        if (response.status === 401) {
            logout();
            throw new Error("Сессия истекла. Пожалуйста, войдите заново.");
        }
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
        await loadChats(); // Обновляем оба списка
        const activeItem = document.querySelector(`.chat-item[data-id="${currentChatId}"]`);
        if (activeItem) activeItem.classList.add('active');
    }
}

// Функция для добавления сообщения в мобильный чат
// (Без изменений)
function addMessageToChatMobile(role, content) {
    const chatDiv = document.getElementById('chat-mobile');
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

// --- (Остальные мобильные функции без изменений) ---
function autoResizeMobile() {
    const userInput = document.getElementById('userInput-mobile');
    userInput.style.height = 'auto';
    const maxHeight = 300;
    userInput.style.height = Math.min(userInput.scrollHeight, maxHeight) + 'px';
}
function displayFileNameMobile() {
    const fileInput = document.getElementById('file-upload-mobile');
    const fileNameDisplay = document.getElementById('file-name-display-mobile');
    if (fileInput.files.length > 0) {
        const file = fileInput.files[0];
        currentFile = file;
        fileNameDisplay.textContent = `Файл: ${file.name}`;
    } else {
        currentFile = null;
        fileNameDisplay.textContent = '';
    }
}
function filterChatsMobile() {
    updateMobileChatsList();
}
function clearFileInputMobile() {
    document.getElementById('file-upload-mobile').value = null;
    document.getElementById('file-name-display-mobile').textContent = '';
    currentFile = null;
}

// Функция для удаления чата в мобильной версии
async function deleteChatMobile(chatId, chatName) {
    if (isStreaming) {
        alert("Нельзя удалить чат во время генерации ответа.");
        return;
    }
    
    // *** ИЗМЕНЕНИЕ: Проверка токена ***
    const token = getToken();
    if (!token) {
        logout();
        return;
    }

    if (!confirm(`Вы уверены, что хотите удалить чат "${chatName}"?`)) {
        return;
    }
    try {
        // *** ИЗМЕНЕНИЕ: Добавляем 'Authorization' header ***
        const response = await fetch('/delete_chat', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify({ chat_id: chatId })
        });

        if (response.status === 401) {
            logout();
            return;
        }
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Не удалось удалить чат');
        }
        chats = chats.filter(c => c.id !== chatId);
        if (currentChatId === chatId) {
            document.getElementById('chat-mobile').innerHTML = '';
            if (chats.length > 0) {
                await setCurrentChat(chats[0].id);
            } else {
                createNewChat();
            }
        }
        updateMobileChatsList(); // Обновляем мобильный список
    } catch (error) {
        console.error("Ошибка удаления чата:", error);
        alert(`Ошибка: ${error.message}`);
    }
}


// --- Обработчики событий ---
// (Без изменений)
const userInput = document.getElementById('userInput');
userInput.addEventListener('input', autoResize);
userInput.addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessageStream();
    }
});
document.getElementById('toggle-sidebar-btn').addEventListener('click', toggleSidebar);

// --- НОВЫЕ ОБРАБОТЧИКИ ДЛЯ АВТОРИЗАЦИИ ---

// Обработчик клика по кнопке пользователя в footer
document.addEventListener('click', function (e) {
    if (e.target.closest('#user-menu-btn')) {
        e.stopPropagation();
        // *** ИЗМЕНЕНИЕ: Проверяем по токену ***
        if (getToken()) {
            openLogoutModal();
        } else {
            openAuthModal();
        }
    }
});

// *** ИЗМЕНЕНИЕ: Обработчик отправки формы входа (получаем токен) ***
document.addEventListener('submit', async function (e) {
    if (e.target.id === 'login-form') {
        e.preventDefault();
        const login = document.getElementById('login-input').value.trim();
        const password = document.getElementById('password-input').value.trim();
        const loginBtn = document.getElementById('login-btn');

        if (!login || !password) {
            alert("Пожалуйста, заполните все поля.");
            return;
        }
        loginBtn.disabled = true;
        loginBtn.textContent = "Вход...";

        try {
            const hashedPassword = await hashPassword(password);
            
            const response = await fetch('/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ login: login, pass_hash: hashedPassword })
            });

            if (response.ok) {
                const data = await response.json();
                
                // *** НОВОЕ: Сохраняем токен и никнейм ***
                storeCredentials(data.access_token, data.nickname);

                document.getElementById('auth-modal').classList.remove('mandatory');
                closeAuthModal();
                console.log(`Пользователь ${data.nickname} вошел.`);

                // Загружаем чаты и устанавливаем первый
                await loadChats();
                if (chats.length > 0) {
                    await setCurrentChat(chats[0].id);
                } else {
                    createNewChat();
                }

            } else {
                const error = await response.json();
                alert(`Ошибка входа: ${error.detail}`);
            }

        } catch (error) {
            console.error("Ошибка сети при входе:", error);
            alert("Не удалось подключиться к серверу.");
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = "Войти";
        }
    }
});

// (Остальные обработчики без изменений)
document.addEventListener('click', function (e) {
    if (e.target.id === 'register-link') {
        e.preventDefault();
        openRegisterModal();
    }
});
document.addEventListener('click', function (e) {
    if (e.target.id === 'confirm-logout') {
        logout();
        closeLogoutModal();
    } else if (e.target.id === 'cancel-logout') {
        closeLogoutModal();
    }
});
window.addEventListener('click', function (event) {
    const authModal = document.getElementById('auth-modal');
    const logoutModal = document.getElementById('logout-modal');
    const registerModal = document.getElementById('register-modal');
    if (event.target === authModal && !authModal.classList.contains('mandatory')) {
        closeAuthModal();
    }
    if (event.target === logoutModal) {
        closeLogoutModal();
    }
    if (event.target === registerModal && !authModal.classList.contains('mandatory')) {
        closeRegisterModal();
    }
});


// *** ИЗМЕНЕНИЕ: Обработчик отправки формы регистрации (получаем токен) ***
document.addEventListener('submit', async function (e) {
    if (e.target.id === 'register-form') {
        e.preventDefault();
        const login = document.getElementById('register-login').value.trim();
        const password = document.getElementById('register-password').value.trim();
        const confirmPassword = document.getElementById('register-confirm-password').value.trim();
        const registerBtn = document.getElementById('register-btn');

        if (!login || !password || !confirmPassword) {
            alert("Пожалуйста, заполните все поля.");
            return;
        }
        if (password !== confirmPassword) {
            alert("Пароли не совпадают.");
            return;
        }
        registerBtn.disabled = true;
        registerBtn.textContent = "Регистрация...";

        try {
            const hashedPassword = await hashPassword(password);
            
            const response = await fetch('/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ login: login, pass_hash: hashedPassword })
            });
            
            if (response.ok) {
                const data = await response.json();
                
                // *** НОВОЕ: Сразу сохраняем токен и никнейм ***
                storeCredentials(data.access_token, data.nickname);

                document.getElementById('auth-modal').classList.remove('mandatory');
                closeRegisterModal();
                console.log(`Пользователь ${data.nickname} зарегистрирован и вошел.`);
                
                // Загружаем чаты (будут пустыми) и создаем новый
                await loadChats();
                createNewChat();

            } else {
                const error = await response.json();
                alert(`Ошибка регистрации: ${error.detail}`);
            }

        } catch (error) {
            console.error("Ошибка сети при регистрации:", error);
            alert("Не удалось подключиться к серверу.");
        } finally {
            registerBtn.disabled = false;
            registerBtn.textContent = "Зарегистрироваться";
        }
    }
});

// (Обработчики ссылок между модальными окнами без изменений)
document.addEventListener('click', function (e) {
    if (e.target.id === 'register-link') {
        e.preventDefault();
        openRegisterModal();
    }
});
document.addEventListener('click', function (e) {
    if (e.target.id === 'back-to-login') {
        e.preventDefault();
        closeRegisterModal();
        openAuthModal();
    }
});