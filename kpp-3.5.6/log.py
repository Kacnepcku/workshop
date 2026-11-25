#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
Модуль логирования.

- Директория: logs/
- Имя файла: {workplace_name}.log
- Каждый день файл начинается заново
- При перезапуске текущий файл архивируется
- Хранится 3 дня
"""

import os
import shutil
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
RETENTION_DAYS = 3

# Текущее состояние
_current_file = None
_current_date = None


def _get_filename(identifier):
    """Возвращает путь к файлу лога для данного идентификатора (IP или workplace_name)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    return os.path.join(LOG_DIR, f"{identifier}.log")


def _archive_old_log(filepath):
    """Сохраняет текущий файл лога с датой перед началом нового."""
    if os.path.exists(filepath):
        base, ext = os.path.splitext(filepath)
        archived = f"{base}_{datetime.now().strftime('%d.%m.%y')}{ext}"
        shutil.copy2(filepath, archived)


def _cleanup_old_logs():
    """Удаляет файлы логов старше RETENTION_DAYS дней."""
    if not os.path.exists(LOG_DIR):
        return
    now = datetime.now()
    for fname in os.listdir(LOG_DIR):
        fpath = os.path.join(LOG_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        # Проверяем возраст
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
        if (now - mtime).days >= RETENTION_DAYS:
            os.remove(fpath)


def init_log(identifier):
    """
    Инициализирует лог-файл для данного идентификатора (IP или workplace_name).

    - При первом вызове создаёт/очищает файл для новой даты
    - При перезапуске архивирует старый файл
    """
    global _current_file, _current_date

    filename = _get_filename(identifier)
    today = datetime.now().date()

    # Если файл уже активен и дата та же — ничего не делаем
    if _current_file == filename and _current_date == today:
        return

    # Если это новый день — архивируем старый файл
    if _current_file and _current_date != today:
        _archive_old_log(_current_file)

    # При первом запуске или смене identifier — архивируем существующий файл
    if os.path.exists(filename) and _current_file != filename:
        _archive_old_log(filename)

    # Очищаем файл для нового дня
    _current_file = filename
    _current_date = today
    with open(filename, 'w', encoding='utf-8'):
        pass  # создаём пустой файл

    # Удаляем старые логи
    _cleanup_old_logs()


def log_message(message):
    """Запись сообщения в лог-файл с временной меткой."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(_current_file, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Ошибка записи лога: {e}")
