// --- Получаем элементы ---
const chatDiv = document.getElementById('chat');
const userInput = document.getElementById('userInput');

// --- User ID ---
let userId = localStorage.getItem('chat_user_id');
if (!userId) {
    userId = crypto.randomUUID();
    localStorage.setItem('chat_user_id', userId);
}
console.log("User ID:", userId);

// --- Авто-рост textarea ---
function autoResize() {
    userInput.style.height = 'auto';
    const maxHeight = 300;
    userInput.style.height = Math.min(userInput.scrollHeight, maxHeight) + 'px';
}

// --- Добавление сообщения ---
function addMessageToChat(role, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = role === 'user' ? 'user-message' : 'ai-message';

    // Для пользователя — просто текст (без Markdown)
    if (role === 'user') {
        const formattedContent = content.replace(/\n/g, '<br>');
        messageDiv.innerHTML = `<strong>Вы:</strong> ${formattedContent}`;
    }
    // Для бота — обрабатываем Markdown
    else {
        // Экранируем HTML-теги в исходном тексте (безопасность)
        const safeContent = content
            .replace(/&/g, '&amp;')
            .replace(/</g, '<')
            .replace(/>/g, '>')
            .replace(/"/g, '&quot;');

        // Преобразуем Markdown в HTML
        const htmlContent = marked.parse(safeContent);

        messageDiv.innerHTML = `<strong>Gemini:</strong> ${htmlContent}`;
    }

    chatDiv.appendChild(messageDiv);
    window.scrollTo(0, document.body.scrollHeight);
}

// --- Отправка сообщения ---
function sendMessage() {
    const message = userInput.value.trim();
    if (!message) return;

    addMessageToChat('user', message);
    userInput.value = '';
    autoResize(); // Сброс высоты после очистки

    fetch('/send_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, user_id: userId })
    })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => {
                    throw new Error(err.detail || 'Ошибка сервера');
                });
            }
            return response.json();
        })
        .then(data => {
            addMessageToChat('ai', data.reply);
        })
        .catch(error => {
            console.error('Ошибка:', error);
            addMessageToChat('ai', `Ошибка: ${error.message}`);
        });
}

// --- Очистка истории ---
function clearHistory() {
    if (!confirm("Вы уверены, что хотите очистить историю чата?")) return;

    fetch('/clear_history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId })
    })
        .then(() => {
            chatDiv.innerHTML = '';
            addMessageToChat('ai', 'История чата очищена.');
        })
        .catch(error => {
            console.error('Ошибка очистки:', error);
            addMessageToChat('ai', 'Не удалось очистить историю.');
        });
}

// --- Обработчики событий ---
userInput.addEventListener('input', autoResize);
userInput.addEventListener('keypress', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// --- Инициализация ---
autoResize();