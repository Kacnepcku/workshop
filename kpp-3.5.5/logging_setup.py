# -*- coding: utf-8 -*-

"""
logging_setup.py — стандартный логгер с ротацией вместо самописного log_message.

Было: открытие файла на каждую запись, отсутствие ротации (work.log рос
бесконечно), «тихий» проглот ошибок записи.
Стало: logging.handlers.RotatingFileHandler (5 файлов по 1 МБ).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import config

_LOGGER_NAME = "kpp"


def setup_logging() -> logging.Logger:
    """Инициализировать (идемпотентно) и вернуть логгер приложения."""
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        config.LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def log_message(message: str, level: int = logging.INFO) -> None:
    """Совместимая с 3.5.4 функция записи в лог."""
    get_logger().log(level, message)
