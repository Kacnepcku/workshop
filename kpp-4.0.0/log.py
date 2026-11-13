#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
Модуль логирования.

<<<<<<< HEAD
Расположение:
  • Всегда локальная папка ./logs рядом с программой (и на Linux, и на Windows).

=======
>>>>>>> 123c5d6 (!!! Окончательное деление на модули !!!)
Логика файлов:
  • {workplace_name}.log — активный лог
  • {workplace_name}_ДД.ММ.ГГ.log — архивы
  • Хранится KEEP_ARCHIVES последних архивов для каждого рабочего места
"""

import os
import shutil
from datetime import datetime

# Директория с программой и папка логов
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_BASE_DIR, "logs")

# Сколько последних архивов хранить для каждого рабочего места
KEEP_ARCHIVES = 3

# Текущее состояние
_current_file = None
_current_date = None
_pending_messages = []  # Буфер для сообщений до инициализации файла


def _ensure_local_log_dir():
    """
    Гарантирует наличие локальной папки ./logs.
    Если с прошлых версий осталась символическая ссылка logs -> /mnt/smb/...,
    удаляет ссылку и создаёт обычную локальную директорию.
    """
    if os.path.islink(_LOG_DIR):
        try:
            os.unlink(_LOG_DIR)
        except OSError as e:
            print(f"[log] Не удалось удалить старую симлинк {_LOG_DIR}: {e}")

    os.makedirs(_LOG_DIR, exist_ok=True)
    return _LOG_DIR


def _get_filename(identifier, log_dir):
    """Путь к активному файлу лога."""
    return os.path.join(log_dir, f"{identifier}.log")


def _file_date(filepath):
    """Дата последней записи в файле (по mtime). None, если файла нет."""
    if not os.path.exists(filepath):
        return None
    return datetime.fromtimestamp(os.path.getmtime(filepath)).date()


def _file_has_content(filepath):
    """Файл существует и не пустой?"""
    try:
        return os.path.getsize(filepath) > 0
    except OSError:
        return False


def _archive_old_log(filepath, file_date):
    """
    Архивирует файл с суффиксом даты последней записи.
    Возвращает путь к архиву или None.
    """
    if not os.path.exists(filepath):
        return None

    base, ext = os.path.splitext(filepath)
    suffix_date = file_date.strftime("%d.%m.%y")
    archived = f"{base}_{suffix_date}{ext}"

    counter = 2
    while os.path.exists(archived):
        archived = f"{base}_{suffix_date}_{counter}{ext}"
        counter += 1

    shutil.move(filepath, archived)
    return archived


def _cleanup_old_logs(identifier, log_dir):
    """
    Оставляет KEEP_ARCHIVES последних архивов для данного identifier.
    Активный файл не трогает.
    """
    if not os.path.exists(log_dir):
        return

    prefix = f"{identifier}_"
    archives = []
    for fname in os.listdir(log_dir):
        if not fname.startswith(prefix) or not fname.endswith(".log"):
            continue
        fpath = os.path.join(log_dir, fname)
        if not os.path.isfile(fpath):
            continue
        archives.append((os.path.getmtime(fpath), fpath))

    archives.sort()
    to_remove = archives[:-KEEP_ARCHIVES] if len(archives) > KEEP_ARCHIVES else []

    for _, fpath in to_remove:
        try:
            os.remove(fpath)
        except OSError as e:
            print(f"Не удалось удалить старый лог {fpath}: {e}")


def init_log(identifier, identifier_ip=None):
    """Инициализирует локальный лог в ./logs для identifier (workplace_name)."""
    global _current_file, _current_date, _pending_messages

    log_dir = _ensure_local_log_dir()
    filename = _get_filename(identifier, log_dir)
    today = datetime.now().date()

    if _current_file == filename and _current_date == today:
        return

    file_date = _file_date(filename)

    if file_date is None:
        with open(filename, "w", encoding="utf-8"):
            pass
    elif file_date == today:
        pass
    else:
        if _file_has_content(filename):
            archived = _archive_old_log(filename, file_date)
            if archived:
                print(f"[log] Старый лог заархивирован: {os.path.basename(archived)}")
        else:
            try:
                os.remove(filename)
            except OSError:
                pass

        with open(filename, "w", encoding="utf-8"):
            pass

    _current_file = filename
    _current_date = today

    if _pending_messages:
        try:
            with open(_current_file, "a", encoding="utf-8") as f:
                for line in _pending_messages:
                    f.write(line)
            _pending_messages.clear()
        except Exception as e:
            print(f"[log] Ошибка записи буфера лога: {e}")

    _cleanup_old_logs(identifier, log_dir)
    print(f"[log] Директория логов: {log_dir}")


def log_message(message):
    """Запись в текущий лог с временной меткой."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"

    if _current_file is None:
        _pending_messages.append(line)
        print(line, end="")
        return

    try:
        with open(_current_file, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"Ошибка записи лога: {e}")