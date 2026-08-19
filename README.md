# Garage Bot — Wialon + Telegram

Бот отслеживает въезд ТС в геозону гаража в Wialon и отправляет карточку-фото в Telegram-группу.

## Быстрый старт

### 1. Настройка `.env`

Откройте `.env` и заполните:

```
TELEGRAM_TOKEN=...       # токен от @BotFather
WIALON_TOKEN=...         # токен Wialon
TELEGRAM_CHAT_ID=...     # ID группы (например -1001234567890)
GARAGE_ZONE_NAME=БКС Гараж  # точное имя геозоны в Wialon
POLL_INTERVAL=60         # опрос каждые 60 секунд
MAINTENANCE_WARN_KM=500  # предупреждение при остатке ≤ 500 км до ТО
```

### 2. Получить Chat ID группы

1. Добавьте бота в группу
2. Добавьте @userinfobot в группу — он пришлёт ID (начинается с `-`)
3. Вставьте ID в `.env`
4. Удалите @userinfobot из группы

### 3. Предпросмотр карточки

```bash
pip install -r requirements.txt
python test_card.py
```

Откроется изображение карточки.

### 4. Запуск

**Windows:**
```
start_bot.bat
```

**Или вручную:**
```bash
pip install -r requirements.txt
python main.py
```

## Структура карточки

- Название ТС + (Водитель)
- Статус: online · въехал в гараж · время
- ⚠ Жёлтая плашка если ТО ≤ MAINTENANCE_WARN_KM км
- Топливо | Пробег | Последний выезд
- Название гаража

## Требования

- Python 3.10+
- pip install -r requirements.txt
