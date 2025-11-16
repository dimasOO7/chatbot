// --- *** НОВЫЕ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ АУТЕНТИФИКАЦИИ *** ---
let currentToken = null; // JWT токен
let isAuthenticated = false; // Флаг авторизации
let currentUserNickname = "WIP"; // Текущий никнейм

// --- Глобальные переменные чата ---
let currentChatId = null;
let chats = [];
let isSidebarCollapsed = false;
let currentFile = null;

// --- Переменные для управления стримингом ---
let isStreaming = false;
let activeFetchController = null;

// --- *** ИЗМЕНЕНИЕ: userId (randomUUID) ПОЛНОСТЬЮ УДАЛЕН. *** ---
// ID пользователя теперь определяется сервером на основе токена.


// --- *** НОВОЕ: Вспомогательная функция для заголовков API *** ---
function getAuthHeaders(isFormData = false) {
    const headers = {};
    if (currentToken) {
        headers['Authorization'] = `Bearer ${currentToken}`;
    }
    if (!isFormData) {
        // 'Content-Type' не нужен для FormData, браузер установит его сам
        headers['Content-Type'] = 'application/json';
    }
    return headers;
}

// --- Функция для установки состояния авторизации (UI) ---
function setAuthState(authenticated, nickname = "WIP") {
    isAuthenticated = authenticated;
    currentUserNickname = nickname;

    // Обновляем ПК версию
    const userMenuBtn = document.getElementById('user-menu-btn');
    const userAvatar = document.getElementById('user-avatar');
    const userNickname = document.getElementById('user-nickname');
    
    if (authenticated) {
        userMenuBtn.classList.add('authenticated');
        userNickname.textContent = nickname;
        if (nickname && nickname.length > 0) {
            userAvatar.textContent = nickname.charAt(0).toUpperCase();
        }
    } else {
        userMenuBtn.classList.remove('authenticated');
        userNickname.textContent = "WIP";
        userAvatar.textContent = "A";
    }

    // Обновляем мобильную версию
    updateMobileAuthState();
}

// --- Функции управления модальными окнами ---
function openAuthModal() {
    document.getElementById('login-error').textContent = '';
    document.getElementById('auth-modal').style.display = 'flex';
    document.getElementById('login-input').focus();
}

function closeAuthModal() {
    document.getElementById('auth-modal').style.display = 'none';
    document.getElementById('login-form').reset();
}

function openRegisterModal() {
    document.getElementById('register-error').textContent = '';
    document.getElementById('auth-modal').style.display = 'none';
    document.getElementById('register-modal').style.display = 'flex';
    document.getElementById('register-login').focus();
}

function closeRegisterModal() {
    document.getElementById('register-modal').style.display = 'none';
    document.getElementById('register-form').reset();
}

function openLogoutModal() {
    document.getElementById('logout-modal').style.display = 'flex';
}

function closeLogoutModal() {
    document.getElementById('logout-modal').style.display = 'none';
}

// --- *** ИЗМЕНЕНИЕ: Функция выхода из системы *** ---
function logout() {
    // Очищаем токен и никнейм
    localStorage.removeItem('chat_token');
    localStorage.removeItem('currentUserNickname');
    currentToken = null;
    
    setAuthState(false, "WIP");
    console.log("Пользователь вышел.");

    // Скрываем приложение, показываем окно входа
    document.getElementById('app-container').style.display = 'none';
    openAuthModal();
}

// --- *** НОВОЕ: Функция инициализации после входа *** ---
async function initializeAuthenticatedApp() {
    // 1. Показываем главный контейнер приложения
    document.getElementById('app-container').style.display = 'flex';

    // 2. Загружаем список чатов
    await loadChats();

    // 3. Выбираем самый новый чат или создаём новый
    if (chats.length > 0) {
        // Устанавливаем первый (самый новый) чат
        await setCurrentChat(chats[0].id); 
    } else {
        // Если чатов нет — создаём новый
        createNewChat(); 
    }

    // 4. Инициализация сайдбара из localStorage
    const savedState = localStorage.getItem('sidebarCollapsed');
    if (savedState === 'true') {
        isSidebarCollapsed = true;
        document.getElementById('sidebar').classList.add('collapsed');
        document.getElementById('app-container').classList.add('sidebar-collapsed');
        document.getElementById('toggle-sidebar-btn').textContent = '←';
    }
}


// --- Инициализация приложения ---
document.addEventListener('DOMContentLoaded', async () => {
    
    // --- *** ИЗМЕНЕНИЕ: Логика проверки аутентификации ---
    const savedToken = localStorage.getItem('chat_token');
    const savedNickname = localStorage.getItem('currentUserNickname') || "WIP";

    if (savedToken) {
        // Если токен есть, считаем пользователя авторизованным
        currentToken = savedToken;
        setAuthState(true, savedNickname);
        
        // Запускаем основное приложение
        await initializeAuthenticatedApp();
        
    } else {
        // Если токена нет, показываем окно входа
        setAuthState(false, "WIP");
        openAuthModal();
    }
    // --- Конец логики аутентификации ---


    // --- Обработчик для кнопки гамбургера на мобильных устройствах ---
    const hamburgerBtn = document.getElementById('hamburger-menu-btn');
    if (hamburgerBtn) {
        hamburgerBtn.addEventListener('click', toggleMobileSidebar);
    }
    
    // --- Обработчик для кнопки закрытия мобильного сайдбара ---
    const closeSidebarBtn = document.getElementById('close-sidebar-btn-mobile');
    if (closeSidebarBtn) {
        closeSidebarBtn.addEventListener('click', toggleMobileSidebar);
    }

    // --- Обработчики для мобильных элементов ---
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

    // --- Обработчик клика по кнопке пользователя в мобильном footer ---
    document.addEventListener('click', function (e) {
        if (e.target.closest('#user-menu-btn-mobile')) {
            e.stopPropagation();
            if (isAuthenticated) {
                openLogoutModal();
            } else {
                // В мобильной версии кнопка профиля не должна открывать вход
                // Вход происходит только при загрузке
                console.log("Пользователь не авторизован");
            }
        }
    });

    // --- Обработчик для поиска в мобильном сайдбаре ---
    const searchInputMobile = document.getElementById('search-chats-mobile');
    if (searchInputMobile) {
        searchInputMobile.addEventListener('input', filterChatsMobile);
    }

    // --- Обработчик для кнопки "Новый чат" в мобильном сайдбаре ---
    const newChatBtnMobile = document.getElementById('new-chat-btn-mobile');
    if (newChatBtnMobile) {
        newChatBtnMobile.onclick = createNewChat;
    }
    
    // --- Обработчик для кнопки "Новый чат" в мобильной шапке ---
    const mobileNewChatBtn = document.getElementById('mobile-new-chat-btn');
    if (mobileNewChatBtn) {
        mobileNewChatBtn.onclick = createNewChat;
    }

    // --- Обновляем мобильный интерфейс при загрузке ---
    // (Это произойдет только если пользователь уже авторизован)
    updateMobileChatsList();
    updateMobileAuthState();
});

// --- *** ИЗМЕНЕНИЕ: Загрузка чатов с токеном *** ---
async function loadChats() {
    try {
        const response = await fetch('/get_chats', {
            method: 'GET', // *** ИЗМЕНЕНИЕ: GET, т.к. user_id в токене ***
            headers: getAuthHeaders() // *** ИЗМЕНЕНИЕ: Добавляем токен ***
            // body: JSON.stringify({ user_id: userId }) <-- УДАЛЕНО
        });

        if (!response.ok) {
            if (response.status === 401) {
                // Если токен невалиден, разлогиниваем
                alert("Сессия истекла. Пожалуйста, войдите снова.");
                logout();
            }
            throw new Error('Не удалось загрузить чаты');
        }

        const data = await response.json();
        chats = data.chats;
        renderChatsList(); // Обновит и ПК, и мобильный список

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

// --- Функция для отображения имени файла ---
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
    renderChatsList(); // Обновит и ПК, и мобильный список
    setCurrentChat(chatId);
    clearFileInput();
    
    // На мобильных устройствах закрываем сайдбар после создания чата
    if (document.getElementById('sidebar-mobile').classList.contains('open')) {
        toggleMobileSidebar();
    }
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
            renderChatsList(); // Обновит и ПК, и мобильный список
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

    // Обновляем ПК-версию
    const chatDiv = document.getElementById('chat');
    chatDiv.innerHTML = '';
    clearFileInput();

    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });
    const activeItem = document.querySelector(`.chat-item[data-id="${chatId}"]`);
    if (activeItem) activeItem.classList.add('active');
    
    // Обновляем мобильную версию
    const chatDivMobile = document.getElementById('chat-mobile');
    chatDivMobile.innerHTML = '';
    clearFileInputMobile();
    const activeItemMobile = document.querySelector(`#chats-list-mobile .chat-item[data-id="${chatId}"]`);
    if (activeItemMobile) activeItemMobile.classList.add('active');
    
    // Обновляем заголовок в мобильной версии
    document.getElementById('mobile-chat-title').textContent = chat.name;
    

    // Если сообщения уже есть локально (например, новый чат)
    if (chat.messages && chat.messages.length > 0) {
        chat.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content); // ПК
            addMessageToChatMobile(msg.role, msg.content); // Мобильный
        });
        return;
    }
    // Если это пустой "Новый чат", выходим (не нужно загружать историю)
    if (chat.name === "Новый чат" && (!chat.messages || chat.messages.length === 0)) {
         return;
    }


    try {
        // *** ИЗМЕНЕНИЕ: Запрос истории чата с токеном ***
        const response = await fetch('/get_chat_history', {
            method: 'POST',
            headers: getAuthHeaders(), // *** ИЗМЕНЕНИЕ: Добавляем токен ***
            body: JSON.stringify({ chat_id: chatId }) // *** ИЗМЕНЕНИЕ: user_id не нужен ***
        });

        if (!response.ok) {
             if (response.status === 401) {
                alert("Сессия истекла. Пожалуйста, войдите снова.");
                logout();
            }
            throw new Error('Не удалось загрузить историю чата');
        }

        const chatHistory = await response.json();
        chatHistory.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
            addMessageToChatMobile(msg.role, msg.content);
        });

    } catch (error) {
        console.error("Ошибка загрузки истории чата:", error);
        addMessageToChat('ai', `Не удалось загрузить историю: ${error.message}`);
        addMessageToChatMobile('ai', `Не удалось загрузить историю: ${error.message}`);
    }
}

// --- *** ИЗМЕНЕНИЕ: Отправка сообщения (с токеном) *** ---
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
    
    // *** ИЗМЕНЕНИЕ: Синхронизируем с мобильной версией ***
    addMessageToChatMobile('user', displayMessage);
    

    const currentChat = chats.find(c => c.id === currentChatId);
    if (!currentChat) return;

    // Локальное добавление сообщения (для нового чата)
    if (!currentChat.messages) {
        currentChat.messages = [];
    }
    currentChat.messages.push({
        role: 'user',
        content: displayMessage,
        timestamp: new Date().toISOString()
    });
    

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
    
    // *** ИЗМЕНЕНИЕ: Создаем такой же div для мобильной версии ***
    const chatDivMobile = document.getElementById('chat-mobile');
    const aiMessageDivMobile = document.createElement('div');
    aiMessageDivMobile.className = 'ai-message';
    const aiMessageContentMobile = document.createElement('p');
    aiMessageDivMobile.innerHTML = '<strong>PNI:</strong> ';
    aiMessageDivMobile.appendChild(aiMessageContentMobile);
    chatDivMobile.appendChild(aiMessageDivMobile);


    let fullReply = "";

    try {
        const formData = new FormData();
        formData.append('message', message);
        // formData.append('user_id', userId); // <-- *** УДАЛЕНО: user_id из токена ***
        formData.append('chat_id', currentChatId);

        if (currentFile) {
            formData.append('file', currentFile);
        }

        clearFileInput();
        clearFileInputMobile(); // *** ИЗМЕНЕНИЕ: Очищаем и мобильный инпут ***

        const response = await fetch('/send_message_stream', {
            method: 'POST',
            // *** ИЗМЕНЕНИЕ: Добавляем токен, isFormData = true ***
            headers: getAuthHeaders(true), 
            body: formData,
            signal: signal
        });

        if (!response.ok) {
            if (response.status === 401) {
                alert("Сессия истекла. Пожалуйста, войдите снова.");
                logout();
            }
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
            
            // *** ИЗМЕНЕНИЕ: Обновляем обе версии (ПК и мобильную) ***
            const htmlContent = marked.parse(fullReply);
            aiMessageContent.innerHTML = htmlContent;
            aiMessageContentMobile.innerHTML = htmlContent;
            
            chatDiv.scrollTop = chatDiv.scrollHeight;
            chatDivMobile.scrollTop = chatDivMobile.scrollHeight;
        }

        // Если это был новый чат, удаляем локальные сообщения,
        // т.к. при следующем переключении они загрузятся с сервера
        if (currentChat.messages) {
            delete currentChat.messages;
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            console.log("Стриминг успешно отменен.");
            if (aiMessageDiv.parentNode === chatDiv) {
                chatDiv.removeChild(aiMessageDiv);
            }
            // *** ИЗМЕНЕНИЕ: Удаляем из мобильной версии при отмене ***
            if (aiMessageDivMobile.parentNode === chatDivMobile) {
                chatDivMobile.removeChild(aiMessageDivMobile);
            }
        } else {
            console.error('Ошибка стриминга:', error);
            const errorMsg = `<strong>Ошибка:</strong> ${error.message}`;
            aiMessageContent.innerHTML = errorMsg;
            aiMessageContentMobile.innerHTML = errorMsg; // *** ИЗМЕНЕНИЕ ***
        }

    } finally {
        isStreaming = false;
        activeFetchController = null;
        disableSidebarActions(false);
        
        // Перезагружаем список чатов, чтобы обновить превью
        await loadChats(); 
        
        // Повторно активируем текущий чат, т.к. renderChatsList() сбрасывает 'active'
        const activeItem = document.querySelector(`.chat-item[data-id="${currentChatId}"]`);
        if (activeItem) activeItem.classList.add('active');
        
        const activeItemMobile = document.querySelector(`#chats-list-mobile .chat-item[data-id="${currentChatId}"]`);
        if (activeItemMobile) activeItemMobile.classList.add('active');
    }
}

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

    // *** ИЗМЕНЕНИЕ: Синхронизируем с мобильной версией ***
    updateMobileChatsList();
}

// --- *** ИЗМЕНЕНИЕ: Удаление чата (с токеном) *** ---
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
            headers: getAuthHeaders(), // *** ИЗМЕНЕНИЕ: Добавляем токен ***
            body: JSON.stringify({ chat_id: chatId }) // *** ИЗМЕНЕНИЕ: user_id не нужен ***
        });

        if (!response.ok) {
             if (response.status === 401) {
                alert("Сессия истекла. Пожалуйста, войдите снова.");
                logout();
            }
            const err = await response.json();
            throw new Error(err.detail || 'Не удалось удалить чат');
        }

        chats = chats.filter(c => c.id !== chatId);

        if (currentChatId === chatId) {
            document.getElementById('chat').innerHTML = '';
            document.getElementById('chat-mobile').innerHTML = ''; // Очищаем мобильный чат
            if (chats.length > 0) {
                await setCurrentChat(chats[0].id);
            } else {
                createNewChat();
            }
        }
        renderChatsList(); // Обновит и ПК, и мобильный список

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

// --- Добавление сообщения в чат (ПК) ---
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
    // ПК
    const list = document.getElementById('chats-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    // Мобильный
    const listMobile = document.getElementById('chats-list-mobile');
    const newChatBtnMobile = document.getElementById('new-chat-btn-mobile');

    if (disable) {
        list.classList.add('disabled-actions');
        newChatBtn.disabled = true;
        listMobile.classList.add('disabled-actions');
        newChatBtnMobile.disabled = true;
    } else {
        list.classList.remove('disabled-actions');
        newChatBtn.disabled = false;
        newChatBtn.onclick = createNewChat;
        
        listMobile.classList.remove('disabled-actions');
        newChatBtnMobile.disabled = false;
        newChatBtnMobile.onclick = createNewChat;
    }
}

// --- *** ФУНКЦИИ ДЛЯ СИНХРОНИЗАЦИИ ПК И МОБИЛЬНОЙ ВЕРСИЙ *** ---
// (В основном дублируют логику, но для мобильных ID)

// Обновление мобильного списка чатов
function updateMobileChatsList() {
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
            toggleMobileSidebar(); // Закрываем сайдбар после выбора чата
        });
        const deleteBtn = item.querySelector('.delete-chat-btn');
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            // *** ИЗМЕНЕНИЕ: Используем единую функцию deleteChat ***
            deleteChat(chat.id, chat.name);
        });
        mobileList.appendChild(item);
    });
}

// Обновление состояния авторизации в мобильной версии
function updateMobileAuthState() {
    const userMenuBtnMobile = document.getElementById('user-menu-btn-mobile');
    const userAvatarMobile = document.getElementById('user-avatar-mobile');
    const userNicknameMobile = document.getElementById('user-nickname-mobile');

    if (isAuthenticated) {
        userMenuBtnMobile.classList.add('authenticated');
        userNicknameMobile.textContent = currentUserNickname;
        if (currentUserNickname && currentUserNickname.length > 0) {
            userAvatarMobile.textContent = currentUserNickname.charAt(0).toUpperCase();
        }
    } else {
        userMenuBtnMobile.classList.remove('authenticated');
        userNicknameMobile.textContent = "WIP";
        userAvatarMobile.textContent = "A";
    }
}

// Переключение мобильного сайдбара
function toggleMobileSidebar() {
    const sidebar = document.getElementById('sidebar-mobile');
    sidebar.classList.toggle('open');
}

// *** ИЗМЕНЕНИЕ: Отправка сообщения из мобильной версии ***
// Эта функция теперь просто вызывает основную sendMessageStream,
// но сначала убеждается, что message и currentFile синхронизированы.
async function sendMessageStreamMobile() {
    const userInputMobile = document.getElementById('userInput-mobile');
    const message = userInputMobile.value.trim();
    
    // Синхронизируем message и file с ПК-версией
    document.getElementById('userInput').value = message;
    
    // Если в мобильной версии был выбран файл (currentFile уже установлен),
    // то sendMessageStream() его подхватит.
    
    // Очищаем мобильное поле
    userInputMobile.value = '';
    autoResizeMobile();

    // Вызываем ОСНОВНУЮ функцию отправки
    await sendMessageStream();
}

// Добавление сообщения в мобильный чат
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

// Авто-растягивание поля ввода в мобильной версии
function autoResizeMobile() {
    const userInput = document.getElementById('userInput-mobile');
    userInput.style.height = 'auto';
    const maxHeight = 300;
    userInput.style.height = Math.min(userInput.scrollHeight, maxHeight) + 'px';
}

// Отображение имени файла в мобильной версии
function displayFileNameMobile() {
    const fileInput = document.getElementById('file-upload-mobile');
    const fileNameDisplay = document.getElementById('file-name-display-mobile');
    if (fileInput.files.length > 0) {
        const file = fileInput.files[0];
        currentFile = file; // *** Глобальная переменная ***
        fileNameDisplay.textContent = `Файл: ${file.name}`;
        
        // Синхронизируем с ПК
        document.getElementById('file-name-display').textContent = `Файл: ${file.name}`;
    } else {
        currentFile = null;
        fileNameDisplay.textContent = '';
        document.getElementById('file-name-display').textContent = '';
    }
}

// Поиск чатов в мобильной версии
function filterChatsMobile() {
    updateMobileChatsList();
}

// Сброс прикрепленного файла в мобильной версии
function clearFileInputMobile() {
    document.getElementById('file-upload-mobile').value = null;
    document.getElementById('file-name-display-mobile').textContent = '';
    currentFile = null;
    // Синхронизируем с ПК
    clearFileInput();
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

// Кнопка сворачивания сайдбара (ПК)
document.getElementById('toggle-sidebar-btn').addEventListener('click', toggleSidebar);

// --- *** НОВЫЕ ОБРАБОТЧИКИ ДЛЯ АВТОРИЗАЦИИ *** ---

// Кнопка пользователя (ПК) -> Выход
document.addEventListener('click', function (e) {
    if (e.target.closest('#user-menu-btn')) {
        e.stopPropagation();
        if (isAuthenticated) {
            openLogoutModal();
        } else {
            // Если не авторизован, эта кнопка не должна открывать вход
            // Вход происходит только при загрузке
            console.log("Пользователь не авторизован");
        }
    }
});

// --- *** ИЗМЕНЕНИЕ: Обработчик формы входа (Login) *** ---
document.addEventListener('submit', function (e) {
    if (e.target.id === 'login-form') {
        e.preventDefault();
        const loginInput = document.getElementById('login-input');
        const passwordInput = document.getElementById('password-input');
        const login = loginInput.value.trim();
        const password = passwordInput.value.trim();
        const errorDiv = document.getElementById('login-error');
        errorDiv.textContent = ''; // Очищаем ошибку

        if (!login || !password) {
            errorDiv.textContent = 'Пожалуйста, заполните все поля.';
            return;
        }

        // Сервер ожидает FormData для /token
        const formData = new FormData();
        formData.append('username', login);
        formData.append('password', password);

        fetch('/token', {
            method: 'POST',
            body: formData
        })
        .then(async response => {
            if (response.ok) {
                return response.json();
            } else {
                // Пытаемся прочитать ошибку
                const errorData = await response.json().catch(() => null);
                const detail = errorData ? errorData.detail : 'Неизвестная ошибка входа';
                throw new Error(detail);
            }
        })
        .then(data => {
            // Успешный вход
            currentToken = data.access_token;
            localStorage.setItem('chat_token', data.access_token);
            // *** ИЗМЕНЕНИЕ: Сервер возвращает 'username' ***
            localStorage.setItem('currentUserNickname', data.username); 
            
            setAuthState(true, data.username);
            closeAuthModal();
            
            // Запускаем основное приложение
            initializeAuthenticatedApp();
            console.log(`Пользователь ${data.username} вошел.`);
        })
        .catch(error => {
            console.error('Ошибка входа:', error);
            errorDiv.textContent = error.message;
        });
    }
});


// --- *** ИЗМЕНЕНИЕ: Обработчик формы регистрации (Register) *** ---
document.addEventListener('submit', function (e) {
    if (e.target.id === 'register-form') {
        e.preventDefault();
        
        const login = document.getElementById('register-login').value.trim();
        const password = document.getElementById('register-password').value.trim();
        const confirmPassword = document.getElementById('register-confirm-password').value.trim();
        const errorDiv = document.getElementById('register-error');
        errorDiv.textContent = ''; // Очищаем ошибку

        if (!login || !password || !confirmPassword) {
            errorDiv.textContent = "Пожалуйста, заполните все поля.";
            return;
        }

        if (password !== confirmPassword) {
            errorDiv.textContent = "Пароли не совпадают.";
            return;
        }

        fetch('/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: login,
                password: password
            })
        })
        .then(async response => {
            if (response.ok) {
                return response.json();
            } else {
                const errorData = await response.json().catch(() => null);
                const detail = errorData ? errorData.detail : 'Неизвестная ошибка регистрации';
                throw new Error(detail);
            }
        })
        .then(data => {
            // Успешная регистрация
            console.log(data.message);
            alert("Регистрация прошла успешно! Теперь вы можете войти.");
            closeRegisterModal();
            openAuthModal();
        })
        .catch(error => {
            console.error('Ошибка регистрации:', error);
            errorDiv.textContent = error.message;
        });
    }
});


// Обработчики для окна выхода (Logout)
document.addEventListener('click', function (e) {
    if (e.target.id === 'confirm-logout') {
        logout();
        closeLogoutModal();
    } else if (e.target.id === 'cancel-logout') {
        closeLogoutModal();
    }
});

// --- Обработчики для перехода между окнами ---
document.addEventListener('click', function (e) {
    if (e.target.id === 'register-link') {
        e.preventDefault();
        openRegisterModal();
    } else if (e.target.id === 'back-to-login') {
        e.preventDefault();
        closeRegisterModal();
        openAuthModal();
    }
});

// --- *** ИЗМЕНЕНИЕ: Обработчик клика по фону (НЕ закрывает окна входа/регистрации) *** ---
window.addEventListener('click', function (event) {
    const logoutModal = document.getElementById('logout-modal');
    
    // Закрываем только окно выхода
    if (event.target === logoutModal) {
        closeLogoutModal();
    }
    
    // Окна auth-modal и register-modal больше нельзя закрыть кликом по фону
});