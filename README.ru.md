# Twitch Chat Downloader

> [🇬🇧 English](README.md) · [🇺🇦 Українська](README.uk.md)

Простое и быстрое приложение (GUI + CLI) для скачивания чата с Twitch VOD. Экспорт в TXT, CSV или просмотр в браузере.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat&logo=python)
![PyQt6](https://img.shields.io/badge/PyQt6-6.5%2B-41CD52?style=flat&logo=qt)
![CLI](https://img.shields.io/badge/CLI-ready-4DAF4C?style=flat)
![License](https://img.shields.io/badge/License-MIT-3DA639?style=flat)

<p align="center">
  <img src="assets/logo.png" width="128" height="128" alt="Twitch Chat Downloader Logo">
</p>

## ✨ Возможности

- **🚀 Быстрая загрузка** — многопоточный парсинг: одновременно сканируются разные участки VOD
- **⚡ Высокая скорость** — до 16 потоков, значительно быстрее однопоточных аналогов
- **🎯 Точный тайминг** — скачивание чата за указанный промежуток времени (Start / End)
- **🖼️ Предпросмотр VOD** *(GUI)* — миниатюра, название, канал и длительность перед загрузкой
- **📤 Три формата экспорта** — TXT, CSV или просмотр в браузере с поиском и фильтрацией
- **🌍 Мультиязычность** *(GUI)* — русский, украинский, английский (переключение флагами)
- **🛑 Отмена в один клик** — кнопка Cancel в GUI или Ctrl+C в CLI
- **⚙️ Настройка потоков** — регулируйте под своё соединение
- **💻 CLI-режим** — скачивание без графического интерфейса, для скриптов и автоматизации

## 📸 Скриншоты

<p align="center">
  <img src="preview.png" width="480" alt="Главное окно приложения">
</p>

<p align="center">
  <img src="preview_chat_browser_export.png" width="480" alt="Просмотр чата в браузере">
</p>

## 📦 Установка

### Требования

- Windows 10 / 11, macOS или Linux
- Python 3.10 или выше
- pip

### Быстрый старт

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

Или просто запустите `run.bat` — скрипт сам установит зависимости и откроет GUI.

## 🎮 Использование

### GUI

1. **Вставьте ссылку на VOD** — например: `https://www.twitch.tv/videos/2796577649`
2. **Дождитесь загрузки превью** — приложение покажет название, канал и длительность
3. **(Опционально) Укажите тайминг** — Start / End для скачивания части чата
4. **Нажмите Download Chat** — начнётся многопоточная загрузка
5. **Экспортируйте результат** — TXT, CSV или Browser (просмотр + поиск/фильтр)

### CLI

```bash
# Скачать весь чат в TXT
python cli.py https://www.twitch.tv/videos/2796577649

# Скачать часть чата
python cli.py 2796577649 --start 10:00 --end 1:30:00 -o chat.txt

# CSV с 8 потоками
python cli.py 2796577649 -f csv -t 8

# HTML-вьювер и открыть в браузере
python cli.py 2796577649 -f browser --open

# Тихо (без прогресс-бара, для скриптов)
python cli.py 2796577649 -q -f csv
```

#### Параметры CLI

| Аргумент | Описание |
|----------|----------|
| `url` | Ссылка на VOD Twitch или числовой ID |
| `-o, --output` | Путь для сохранения (по умолчанию — авто из видео) |
| `-f, --format` | Формат: `txt` (по умолч.), `csv`, `browser`/`html` |
| `-t, --threads` | Количество потоков (1–16, умолч. 4) |
| `--start` | Начало — `MM:SS` или `HH:MM:SS` |
| `--end` | Конец — `MM:SS` или `HH:MM:SS` |
| `--open` | Открыть результат (HTML) в браузере |
| `-q, --quiet` | Без прогресс-бара, только итог |

**Ctrl+C** для безопасной отмены.

## 🧵 Настройка потоков

| Потоков | Скорость | Нагрузка на сеть |
|---------|----------|------------------|
| 1–2 | Низкая | Минимальная |
| 4–6 | Средняя | Рекомендуется |
| 8–16 | Высокая | Для быстрых соединений |

## 📁 Структура проекта

```
twitch-chat-downloader/
├── main.py                # GUI-приложение на PyQt6
├── cli.py                 # Консольная версия
├── chat_downloader.py     # Движок скачивания (Twitch GQL)
├── worker.py              # Фоновый поток (только для GUI)
├── l10n.py                # Локализация (EN/RU/UK)
├── requirements.txt       # Зависимости
├── run.bat                # Быстрый запуск на Windows
├── assets/
│   ├── logo.png           # Иконка приложения
│   └── flags/             # SVG-флаги
└── README.md
```

## 🛠️ Технические детали

- **GUI**: PyQt6, кастомный рендеринг циклического прогресса и флагов через QPainter
- **CLI**: Чистый Python (argparse), никаких GUI-зависимостей
- **API**: Twitch GQL (persisted query `VideoCommentsByOffsetOrCursor`)
- **Сканирование**: посегментное (шаг 30 секунд) — обход блокировки cursor-пагинации
- **Сеть**: httpx, многопоточность через `ThreadPoolExecutor`

## 📄 Форматы экспорта

### TXT
```
[00:00] username1: привет!
[00:05] username2: как дела?
[00:12] username1: норм
```

### CSV
```
Timestamp,TimeInVideo,Username,Login,Message
2024-01-01T00:00:00Z,00:00,username1,user1,привет!
```

### Browser
Встроенная HTML-страница с поиском по тексту, фильтром по пользователям, сортировкой.

## 📜 Лицензия

MIT — делайте что хотите, но упоминание автора приветствуется.
