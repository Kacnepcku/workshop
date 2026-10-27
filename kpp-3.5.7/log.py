#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
Модуль логирования.

Расположение:
  • Основной путь: logs/ рядом с программой
    (может быть обычной папкой или символической ссылкой)
  • Резервный путь (если основной недоступен):
      Linux:   /mnt/smb/1_ОБМЕН/Цех/WSHP_LOG/{MY_IP}/
      Windows: \\synas\work\1_ОБМЕН\Цех\WSHP_LOG\{MY_IP}\
  • Аварийный путь: logs_local/ рядом с программой

Логика файлов:
  • {workplace_name}.log — активный лог
  • {workplace_name}_ДД.ММ.ГГ.log — архивы
  • Хранится KEEP_ARCHIVES последних архивов для каждого рабочего места
"""

import os
import sys
import shutil
from datetime import datetime

# Директория с программой
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Сколько последних архивов хранить для каждого рабочего места
KEEP_ARCHIVES = 3

# Текущее состояние
_current_file = None
_current_date = None


def _resolve_log_dir(identifier_ip=None):
    """
    Определяет директорию для логов.

    Приоритет:
      1. logs/ рядом с программой (может быть символической ссылкой)
      2. Резервный сетевой путь с {MY_IP}
      3. Локальный logs_local/ рядом с программой

    Возвращает (путь, описание).
    """
    # 1. Основной путь
    primary = os.path.join(_BASE_DIR, "logs")
    if _ensure_writable_dir(primary):
        return primary, "primary (logs/)"

    # 2. Резервный путь по IP
    ip_suffix = identifier_ip if identifier_ip else "unknown"
    if sys.platform == 'linux':
        fallback = f"/mnt/smb/1_ОБМЕН/Цех/WSHP_LOG/{ip_suffix}"
    elif sys.platform == 'win32':
        fallback = rf"\\synas\work\1_ОБМЕН\Цех\WSHP_LOG\{ip_suffix}"
    else:
        fallback = None

    if fallback and _ensure_writable_dir(fallback):
        return fallback, f"fallback ({fallback})"

    # 3. Аварийный локальный путь
    local = os.path.join(_BASE_DIR, "logs_local")
    os.makedirs(local, exist_ok=True)
    return local, f"local ({local})"


def _ensure_writable_dir(path):
    """
    Проверяет, что директория существует и доступна для записи.
    Если её нет — пытается создать.
    Возвращает True / False.
    """
    try:
        os.makedirs(path, exist_ok=True)
        # Пробуем создать временный файл
        probe = os.path.join(path, ".__write_test__")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


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
        if not fname.startswith(prefix):
            continue
        if not fname.endswith(".log"):
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
    """
    Инициализирует лог для identifier (обычно workplace_name).

    identifier_ip — IP (последний октет), используется только для
    резервного пути, если основной logs/ недоступен.
    """
    global _current_file, _current_date

    log_dir, location = _resolve_log_dir(identifier_ip)
    filename = _get_filename(identifier, log_dir)
    today = datetime.now().date()

    # Уже инициализирован в этом процессе — ничего не делаем
    if _current_file == filename and _current_date == today:
        return

    file_date = _file_date(filename)

    if file_date is None:
        with open(filename, "w", encoding="utf-8"):
            pass
    elif file_date == today:
        # Сегодняшний файл — продолжаем
        pass
    else:
        # Прошлый день — архивируем
        if _file_has_content(filename):
            archived = _archive_old_log(filename, file_date)
            if archived:
                print(f"Лог заархивирован: {os.path.basename(archived)}")
        else:
            try:
                os.remove(filename)
            except OSError:
                pass

        with open(filename, "w", encoding="utf-8"):
            pass

    _current_file = filename
    _current_date = today

    _cleanup_old_logs(identifier, log_dir)

    # Служебное сообщение о расположении лога
    print(f"[log] Используется директория: {location}")


def log_message(message):
    """Запись в текущий лог с временной меткой."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(_current_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Ошибка записи лога: {e}")