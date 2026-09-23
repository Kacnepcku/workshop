#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
config.py — конфигурация приложения kpp 3.5.5.

Все настройки читаются из переменных окружения (опционально — из файла .env
рядом с main.py). Пароль БД больше не является константой исходного кода.

Переменные окружения:
    KPP_DB_HOST, KPP_DB_PORT, KPP_DB_USER, KPP_DB_PASSWORD, KPP_DB_NAME
    KPP_MY_IP            — номер рабочего места (последний октет IP);
                           по умолчанию определяется через `hostname -I`
    KPP_IMAGE_FOLDER     — каталог изображений деталей
    KPP_LOG_FILE         — файл журнала
"""

import os
import subprocess
import sys


def _load_dotenv(path: str = ".env") -> None:
    """Минимальный загрузчик .env (KEY=VALUE, строки # — комментарии)."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# Определение ОС и путей ========================================================================
if sys.platform == "linux":
    power_off = "systemctl poweroff"
    _default_log = "work.log"
    _default_images = "/mnt/smb/ПВХ/JPG"
    _default_ip = subprocess.run(
        "hostname -I | awk -F'.' '{print $NF}'",
        shell=True, capture_output=True, text=True,
    ).stdout.strip()
elif sys.platform == "win32":
    # Исправлено: корректный UNC-путь (было «ПBX» и избыточное экранирование)
    # и современная синтаксически верная команда выключения.
    power_off = "shutdown /s /t 0"
    _default_log = "test.log"
    _default_images = r"\\synas\work\ПВХ\JPG"
    _default_ip = "99"
else:
    raise RuntimeError(f"Неподдерживаемая платформа: {sys.platform}")

LOG_FILE = os.environ.get("KPP_LOG_FILE", _default_log)
image_folder = os.environ.get("KPP_IMAGE_FOLDER", _default_images)
MY_IP = os.environ.get("KPP_MY_IP", _default_ip)

# Параметры подключения к БД ====================================================================
DB_HOST = os.environ.get("KPP_DB_HOST", "192.168.0.10")
DB_PORT = int(os.environ.get("KPP_DB_PORT", "3306"))
DB_USER = os.environ.get("KPP_DB_USER", "workshop")
# ВНИМАНИЕ: значение по умолчанию оставлено только для обратной совместимости.
# В продакшене задавайте пароль через KPP_DB_PASSWORD (env или .env).
DB_PASSWORD = os.environ.get("KPP_DB_PASSWORD", "w0rK5h0p")
DB_NAME = os.environ.get("KPP_DB_NAME", "workshop")
DB_CHARSET = "utf8"

CONNECT_TIMEOUT_SEC = int(os.environ.get("KPP_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT_SEC = int(os.environ.get("KPP_READ_TIMEOUT", "10"))

# Константы приложения ===========================================================================
CODE_POWEROFF = "12345"      # код сканирования для выключения ПК
PREFIX_WORKER = "2200"       # префикс штрих-кода сотрудника

GRI_IMPOST = "3"             # группа «импост» — не регистрируется
GRI_FRAME = "r"              # рама
GRI_SASH = "s"               # створка

AUTO_UPDATE_MS = 60_000      # период автообновления списка сотрудников
RECONNECT_MS = 5_000         # пауза между попытками подключения к БД
RESIZE_DEBOUNCE_MS = 150     # антидребезг перерисовки изображения при ресайзе

# Бизнес-константа: ширина профиля ПВХ (мм), вычитается из габаритов изделия.
# Ранее была «магической шестёркой», продублированной в db.py и app.py.
PROFILE_OFFSET_MM = 6
