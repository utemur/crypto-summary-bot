# Crypto Summary Bot

Telegram бот для получения аналитической информации о криптовалютном рынке с использованием AI-суммаризации.

## 🚀 Возможности

- 📊 **AI-сводки рынка** - автоматические анализы с использованием GPT
- 📈 **Топ монет** - лучшие и худшие монеты за 24 часа
- 💰 **Поиск монет** - информация о конкретных криптовалютах
- 💼 **Портфолио** - отслеживание криптовалютных активов
- 🔔 **Уведомления** - настройка алертов о ценах
- ⏰ **Ежедневные сводки** - автоматические отчеты в заданное время

## 🛠 Технологии

- Python 3.11
- python-telegram-bot
- OpenAI API
- CoinGecko API
- PostgreSQL

## 📋 Команды

- `/start` - главное меню
- `/summary` - сводка рынка
- `/gainers` - топ монет
- `/price <монета>` - цена монеты
- `/buy <монета> <количество> <цена>` - добавить покупку
- `/sell <монета> <количество> <цена>` - добавить продажу
- `/portfolio` - обзор портфолио
- `/transactions` - история транзакций
- `/alert <монета> <оператор> <цена>` - добавить уведомление
- `/myalerts` - мои уведомления
- `/delete <ID>` - удалить уведомление
- `/settime HH:MM` - время сводок

## 🔧 Установка

### Локальная разработка

1. Клонируйте репозиторий
2. Установите PostgreSQL
3. Создайте базу данных: `createdb crypto_bot`
4. Установите зависимости: `pip install -r requirements.txt`
5. Создайте файл `.env` с переменными окружения
6. Запустите бота: `python main.py`

### Переменные окружения

```env
# Обязательные
TELEGRAM_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key

# Опциональные
GPT_MODEL=gpt-3.5-turbo-0125

# PostgreSQL (для локальной разработки)
DB_HOST=localhost
DB_NAME=crypto_bot
DB_USER=postgres
DB_PASSWORD=your_password
DB_PORT=5432

# DATABASE_URL (автоматически устанавливается Render)
DATABASE_URL=postgresql://user:password@host:port/database
```

## 📦 Развертывание на Render

### 1. Подготовка

1. Создайте аккаунт на [Render.com](https://render.com)
2. Подключите ваш GitHub репозиторий
3. Убедитесь, что все файлы загружены в репозиторий

### 2. Создание сервисов

1. **Создайте PostgreSQL Database**:
   - New + → PostgreSQL
   - Name: `crypto-bot-db`
   - Database: `crypto_bot`
   - User: `crypto_bot_user`

2. **Создайте Web Service**:
   - New + → Web Service
   - Connect your repository
   - Name: `crypto-summary-bot`
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python main.py`

### 3. Настройка переменных окружения

В настройках Web Service добавьте:

- `TELEGRAM_TOKEN` = ваш токен бота от @BotFather
- `OPENAI_API_KEY` = ваш ключ API от OpenAI
- `GPT_MODEL` = `gpt-3.5-turbo-0125`
- `DATABASE_URL` = автоматически подключится к PostgreSQL

### 4. Deploy

Нажмите "Create Web Service" и дождитесь завершения деплоя.

## 🗄 База данных

Бот использует PostgreSQL с следующими таблицами:

- **users** - информация о пользователях
- **alerts** - уведомления о ценах
- **portfolio** - текущие позиции в портфолио
- **transactions** - история покупок/продаж

## 🔍 Мониторинг

- **Логи**: доступны в панели Render
- **База данных**: управление через Render Dashboard
- **Метрики**: автоматически собираются Render

## 🚨 Troubleshooting

### Проблемы с подключением к БД
- Проверьте `DATABASE_URL` в переменных окружения
- Убедитесь, что PostgreSQL сервис запущен

### Ошибки с API
- Проверьте правильность токенов
- Убедитесь, что API ключи активны

### Проблемы с деплоем
- Проверьте логи в Render Dashboard
- Убедитесь, что все зависимости указаны в `requirements.txt`

## 📄 Лицензия

MIT License 