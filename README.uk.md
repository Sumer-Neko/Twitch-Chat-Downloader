# Twitch Chat Downloader

> [🇬🇧 English](README.md) · [🇷🇺 Русский](README.ru.md)

Проста та швидка програма (GUI + CLI) для завантаження чату з Twitch VOD. Експорт у TXT, CSV або перегляд у браузері.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat&logo=python)
![PyQt6](https://img.shields.io/badge/PyQt6-6.5%2B-41CD52?style=flat&logo=qt)
![CLI](https://img.shields.io/badge/CLI-ready-4DAF4C?style=flat)
![License](https://img.shields.io/badge/License-MIT-3DA639?style=flat)

<p align="center">
  <img src="assets/logo.png" width="128" height="128" alt="Twitch Chat Downloader Logo">
</p>

## ✨ Можливості

- **🚀 Швидке завантаження** — багатопотоковий парсинг: одночасно скануються різні ділянки VOD
- **⚡ Висока швидкість** — до 16 потоків, значно швидше однопотокових аналогів
- **🎯 Точний таймінг** — завантаження чату за вказаний проміжок часу (Start / End)
- **🖼️ Попередній перегляд VOD** *(GUI)* — мініатюра, назва, канал і тривалість перед завантаженням
- **📤 Три формати експорту** — TXT, CSV або перегляд у браузері з пошуком і фільтрацією
- **🌍 Багатомовність** *(GUI)* — українська, російська, англійська (перемикання прапорцями)
- **🛑 Скасування в один клік** — кнопка Cancel у GUI або Ctrl+C у CLI
- **⚙️ Налаштування потоків** — регулюйте під своє з'єднання
- **💻 CLI-режим** — завантаження без графічного інтерфейсу, для скриптів та автоматизації

## 📸 Скріншоти

<p align="center">
  <img src="preview.png" width="480" alt="Головне вікно програми">
</p>

<p align="center">
  <img src="preview_chat_browser_export.png" width="480" alt="Перегляд чату в браузері">
</p>

## 📦 Встановлення

### Вимоги

- Windows 10 / 11, macOS або Linux
- Python 3.10 або вище
- pip

### Швидкий старт

```bash
git clone https://github.com/Sumer-Neko/Twitch-Chat-Downloader.git
cd TwitchChatDownloader
pip install -r requirements.txt
```

**Запуск GUI:**
```bash
python main.py
```

**Запуск CLI:**
```bash
python cli.py https://www.twitch.tv/videos/2796577649
```

Або просто запустіть `run.bat` — скрипт сам встановить залежності та відкриє GUI.

## 🎮 Використання

### GUI

1. **Вставте посилання на VOD** — наприклад: `https://www.twitch.tv/videos/2796577649`
2. **Зачекайте на завантаження прев'ю** — програма покаже назву, канал і тривалість
3. **(Опціонально) Вкажіть таймінг** — Start / End для завантаження частини чату
4. **Натисніть Download Chat** — почнеться багатопотокове завантаження
5. **Експортуйте результат** — TXT, CSV або Browser (перегляд + пошук/фільтр)

### CLI

```bash
# Завантажити весь чат у TXT
python cli.py https://www.twitch.tv/videos/2796577649

# Завантажити частину чату
python cli.py 2796577649 --start 10:00 --end 1:30:00 -o chat.txt

# CSV з 8 потоками
python cli.py 2796577649 -f csv -t 8

# HTML-в'ювер і відкрити в браузері
python cli.py 2796577649 -f browser --open

# Тихо (без прогрес-бару, для скриптів)
python cli.py 2796577649 -q -f csv
```

#### Параметри CLI

| Аргумент | Опис |
|----------|------|
| `url` | Посилання на VOD Twitch або числовий ID |
| `-o, --output` | Шлях для збереження (за замовчуванням — авто з відео) |
| `-f, --format` | Формат: `txt` (за замовч.), `csv`, `browser`/`html` |
| `-t, --threads` | Кількість потоків (1–16, за замовч. 4) |
| `--start` | Початок — `MM:SS` або `HH:MM:SS` |
| `--end` | Кінець — `MM:SS` або `HH:MM:SS` |
| `--open` | Відкрити результат (HTML) у браузері |
| `-q, --quiet` | Без прогрес-бару, тільки підсумок |

**Ctrl+C** для безпечного скасування.

## 🧵 Налаштування потоків

| Потоків | Швидкість | Навантаження на мережу |
|---------|-----------|------------------------|
| 1–2 | Низька | Мінімальне |
| 4–6 | Середня | Рекомендується |
| 8–16 | Висока | Для швидких з'єднань |

## 📁 Структура проекту

```
twitch-chat-downloader/
├── main.py                # GUI-додаток на PyQt6
├── cli.py                 # Консольна версія
├── chat_downloader.py     # Рушій завантаження (Twitch GQL)
├── worker.py              # Фоновий потік (тільки для GUI)
├── l10n.py                # Локалізація (EN/RU/UK)
├── requirements.txt       # Залежності
├── run.bat                # Швидкий запуск на Windows
├── assets/
│   ├── logo.png           # Іконка додатка
│   └── flags/             # SVG-прапорці
└── README.md
```

## 🛠️ Технічні деталі

- **GUI**: PyQt6, кастомний рендеринг циклічного прогресу та прапорців через QPainter
- **CLI**: Чистий Python (argparse), жодних GUI-залежностей
- **API**: Twitch GQL (persisted query `VideoCommentsByOffsetOrCursor`)
- **Сканування**: посегментне (крок 30 секунд) — обхід блокування cursor-пагінації
- **Мережа**: httpx, багатопотоковість через `ThreadPoolExecutor`

## 📄 Формати експорту

### TXT
```
[00:00] username1: привіт!
[00:05] username2: як справи?
[00:12] username1: норм
```

### CSV
```
Timestamp,TimeInVideo,Username,Login,Message
2024-01-01T00:00:00Z,00:00,username1,user1,привіт!
```

### Browser
Вбудована HTML-сторінка з пошуком по тексту, фільтром за користувачами, сортуванням.

## 📜 Ліцензія

MIT — робіть що хочете, але згадка автора вітається.

