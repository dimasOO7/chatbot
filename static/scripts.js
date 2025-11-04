// --- Глобальные переменные ---
let currentChatId = null;
let chats = []; 
let userId = localStorage.getItem('chat_user_id');

// --- Новые переменные для управления стримингом ---
let isStreaming = false; // Флаг для отслеживания активного стриминга
let activeFetchController = null; // Контроллер для отмены запроса

if (!userId || userId === "") {
    if (typeof window.crypto.randomUUID === 'function') {
        userId = window.crypto.randomUUID();
    } else {
        userId = 'temp-user-' + Date.now();
    }
    localStorage.setItem('chat_user_id', userId);
}
console.log("User ID:", userId);

// --- Инициализация приложения ---
document.addEventListener('DOMContentLoaded', async () => {
    // 1. Загружаем список чатов с сервера
    await loadChats(); 
    
    // 2. Выбираем самый новый (первый в списке) или создаем новый
    if (chats.length > 0) {
        await setCurrentChat(chats[0].id);
    } else {
        createNewChat(); 
    }
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


// --- Функция для создания НОВОГО (локального) чата ---
function createNewChat() {
    const chatId = crypto.randomUUID ? crypto.randomUUID() : 'chat-' + Date.now();
    const newChat = {
        id: chatId,
        name: "Новый чат",
        messages: [], // Важно: маркер нового/локального чата
    };

    // Добавляем в начало списка (unshift)
    chats.unshift(newChat);
    renderChatsList();
    setCurrentChat(chatId); 
}

// --- Установка текущего чата (ЗАГРУЗКА ИСТОРИИ) ---
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
    
    // ДОБАВЛЕНО: Блокировка переключения, если идет стриминг
    if (isStreaming) {
        console.log("🚫 Невозможно переключить чат во время стриминга.");
        return; 
    }

    // --- ДОБАВЛЕННАЯ ЛОГИКА: Удаление пустого локального чата перед переключением ---
    const previousChat = chats.find(c => c.id === currentChatId);
    if (previousChat && previousChat.id !== chatId) {
        // Проверяем: 
        // 1. Существует ли предыдущий чат?
        // 2. Является ли он локальным (есть ли массив messages)?
        // 3. Пуст ли этот массив messages?
        if (previousChat.messages && previousChat.messages.length === 0) {
            console.log(`🗑️ Удаление пустого локального чата: ${previousChat.name} (ID: ${previousChat.id})`);
            
            // Удаляем из локального кэша
            chats = chats.filter(c => c.id !== currentChatId);
            
            // Перерисовываем список, чтобы он пропал
            renderChatsList();
        }
    }
    // --- КОНЕЦ ДОБАВЛЕННОЙ ЛОГИКИ ---
    
    // Если идет стриминг, отменяем его (это должно быть уже обработано проверкой выше, но оставим на всякий случай, если код где-то вызывает напрямую)
    if (isStreaming && activeFetchController) {
        activeFetchController.abort(); // Отмена текущего запроса
        isStreaming = false;
        activeFetchController = null;
        console.log("⚠️ Активный стриминг отменен из-за смены чата.");
    }
    
    currentChatId = chatId;
    const chat = chats.find(c => c.id === chatId);
    if (!chat) {
         // После удаления пустого чата, chatId может стать неактуальным, 
         // поэтому ищем первый актуальный в обновленном списке
         console.error(`Чат с ID ${chatId} не найден в локальном кэше. Перезагрузка или переключение.`);
         if (chats.length === 0) {
            createNewChat(); // Если вообще ничего не осталось
            return;
         }
         // Устанавливаем самый новый чат в списке, чтобы избежать ошибки
         await setCurrentChat(chats[0].id);
         return;
    }

    // Очищаем и перерисовываем чат
    const chatDiv = document.getElementById('chat');
    chatDiv.innerHTML = '';

    // Выделяем активный чат
    document.querySelectorAll('.chat-item').forEach(item => {
        item.classList.remove('active');
    });
    const activeItem = document.querySelector(`.chat-item[data-id="${chatId}"]`);
    if (activeItem) activeItem.classList.add('active');

    // Если у чата есть свойство 'messages' (массив) - это локальный
    if (chat.messages) {
        chat.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
        });
        return; 
    }

    // --- Если это существующий чат, грузим его ПОЛНУЮ историю ---
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
        
        // Рендерим сообщения из загруженной истории
        chatHistory.messages.forEach(msg => {
            addMessageToChat(msg.role, msg.content);
        });

    } catch (error) {
        console.error("Ошибка загрузки истории чата:", error);
        addMessageToChat('ai', `Не удалось загрузить историю: ${error.message}`);
    }
}

// --- Отправка сообщения (СТРИМИНГ) ---
async function sendMessageStream() {
    if (isStreaming) {
        console.log("🚫 Уже идет стриминг. Подождите или отмените.");
        return; 
    }
    
    const userInput = document.getElementById('userInput');
    const message = userInput.value.trim();
    if (!message) return;

    // Добавляем сообщение пользователя в UI
    addMessageToChat('user', message);
    userInput.value = '';
    autoResize();

    const currentChat = chats.find(c => c.id === currentChatId);
    if (!currentChat) return;

    // Если это локальный новый чат, сохраняем сообщение в
    // локальный массив, чтобы оно не пропало при ошибке
    if (currentChat.messages) {
         currentChat.messages.push({
            role: 'user',
            content: message,
            timestamp: new Date().toISOString()
        });
    }
    
    // --- Инициализация стриминга ---
    isStreaming = true;
    activeFetchController = new AbortController();
    const signal = activeFetchController.signal;
    
    // ДОБАВЛЕНО: Блокировка действий в сайдбаре
    disableSidebarActions(true);
    
    // Создаем ПУСТОЙ элемент для ответа AI
    const chatDiv = document.getElementById('chat');
    const aiMessageDiv = document.createElement('div');
    aiMessageDiv.className = 'ai-message';
    
    // Создаем элемент <p> для рендеринга Markdown
    const aiMessageContent = document.createElement('p');
    aiMessageDiv.innerHTML = '<strong>PNI:</strong> '; 
    aiMessageDiv.appendChild(aiMessageContent); 
    chatDiv.appendChild(aiMessageDiv);
    
    let fullReply = "";
    
    try {
        const response = await fetch('/send_message_stream', { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                user_id: userId,
                chat_id: currentChatId
            }),
            signal: signal // Передаем сигнал для отмены
        });

        if (!response.ok) {
            const errText = await response.text();
            throw new Error(`Ошибка API (${response.status}): ${errText}`);
        }

        // --- Читаем поток ---
        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value);
            fullReply += chunk;
            
            // Рендерим Markdown на лету
            aiMessageContent.innerHTML = marked.parse(fullReply);
            
            // Прокручиваем вниз
            chatDiv.scrollTop = chatDiv.scrollHeight;
        }

        // Если это был новый чат, его свойство .messages нам больше не нужно
        // Мы удаляем его, чтобы он загружался с сервера как "сохраненный"
        if (currentChat.messages) {
            delete currentChat.messages;
        }

    } catch (error) {
        // Проверяем, была ли ошибка вызвана отменой (переключением чата)
        if (error.name === 'AbortError') {
            console.log("Стриминг успешно отменен.");
            // Удаляем неполный элемент AI из DOM
            if (aiMessageDiv.parentNode === chatDiv) {
                chatDiv.removeChild(aiMessageDiv);
            }
        } else {
            console.error('Ошибка стриминга:', error);
            aiMessageContent.innerHTML = `<strong>Ошибка:</strong> ${error.message}`;
        }
    
    } finally {
        // --- Финализация стриминга ---
        isStreaming = false;
        activeFetchController = null;
        
        // ДОБАВЛЕНО: Разблокировка действий в сайдбаре
        disableSidebarActions(false);

        // Перезагружаем список чатов, чтобы обновить имя и позицию
        await loadChats();
        
        // Повторно выделяем активный чат, т.к. renderChatsList() сбросил выделение
        const activeItem = document.querySelector(`.chat-item[data-id="${currentChatId}"]`);
        if (activeItem) activeItem.classList.add('active');
    }
}


// --- Рендер списка чатов ---
function renderChatsList() {
    const list = document.getElementById('chats-list');
    list.innerHTML = '';

    // Если чаты заблокированы, не даем им быть кликабельными
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
            <span class="avatar">💬</span>
            <div class="chat-info">
                <div class="chat-name">${chat.name}</div>
                <div class="chat-preview">${lastText}</div>
            </div>
            <span class="delete-chat-btn" title="Удалить чат">🗑️</span>
        `;

        // Клик по чату
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

// --- Функция удаления чата (Решение Проблемы 1) ---
async function deleteChat(chatId, chatName) {
    // ДОБАВЛЕНО: Блокировка удаления, если идет стриминг
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

        // Удаляем из локального кэша
        chats = chats.filter(c => c.id !== chatId);
        
        // --- Логика после удаления ---
        if (currentChatId === chatId) {
            // 1. Очищаем окно чата
            document.getElementById('chat').innerHTML = '';

            // 2. Переключаемся на самый новый (первый) или создаем новый
            if (chats.length > 0) {
                // Переключение на новый активный чат
                await setCurrentChat(chats[0].id);
            } else {
                // Если чатов не осталось, создаем новый
                createNewChat();
            }
            
            // 3. Вызов setCurrentChat уже выполнил renderChatsList()
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


// --- Авто-рост textarea ---
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

// --- Функция блокировки/разблокировки действий в сайдбаре (НОВАЯ ФУНКЦИЯ) ---
function disableSidebarActions(disable) {
    const list = document.getElementById('chats-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    const newChatBtnElement = document.getElementById('new-chat-btn');
    
    if (disable) {
        list.classList.add('disabled-actions');
        newChatBtn.disabled = true;
        // Блокируем создание нового чата, если он не вызван из createNewChat()
        newChatBtnElement.onclick = () => { console.log("🚫 Действие заблокировано во время стриминга."); };
    } else {
        list.classList.remove('disabled-actions');
        newChatBtn.disabled = false;
        // Восстанавливаем оригинальный обработчик
        newChatBtnElement.onclick = createNewChat;
    }
}


// --- Переключение модели (WIP) ---
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