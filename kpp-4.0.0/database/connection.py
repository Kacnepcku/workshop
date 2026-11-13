#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import socket
from contextlib import contextmanager
import pymysql
from config import AppConfig
from log import log_message


class DatabaseError(Exception):
    """Ошибка соединения или выполнения запроса к БД."""


class Database:
    """Управляет подключением к MySQL и транзакциями."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._conn = None

    def is_port_open(self, timeout: float = 0.5) -> bool:
        """Быстрая проверка доступности сервера БД по TCP."""
        try:
            with socket.create_connection((self.cfg.db_host, self.cfg.db_port), timeout=timeout):
                return True
        except OSError:
            return False

    def _create_connection(self):
        return pymysql.connect(
            host=self.cfg.db_host,
            port=self.cfg.db_port,
            user=self.cfg.db_user,
            password=self.cfg.db_password,
            database=self.cfg.db_name,
            charset=self.cfg.db_charset,
            autocommit=False,
            connect_timeout=3,
            read_timeout=5,
            write_timeout=5,
        )

    def drop(self) -> None:
        """Принудительно закрывает сокет без отправки сетевых пакетов."""
        if self._conn is not None:
            try:
                self._conn.force_close()
            except Exception:
                pass
            self._conn = None

    def close(self) -> None:
        """Штатное закрытие соединения при выходе."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def ensure_connected(self) -> bool:
        """Проверяет живое соединение или переподключается."""
        if not self.is_port_open(timeout=0.5):
            self.drop()
            return False

        if self._conn is not None:
            try:
                self._conn.ping(reconnect=False)
                return True
            except Exception as e:
                log_message(f"Сессия БД не отвечает ({e}), переподключаемся...")
                self.drop()

        try:
            self._conn = self._create_connection()
            log_message("Соединение с БД установлено")
            return True
        except Exception as e:
            self.drop()
            log_message(f"Не удалось подключиться к БД: {e}")
            return False

    def _safe_rollback(self) -> None:
        if self._conn is not None and self.is_port_open(timeout=0.3):
            try:
                self._conn.rollback()
            except Exception:
                self.drop()

    @contextmanager
    def transaction(self):
        """
        Контекстный менеджер для работы с БД:
        - проверяет соединение;
        - выдает курсор;
        - делает commit() при успешном выходе из блока;
        - делает safe_rollback() при любом исключении.
        """
        if not self.ensure_connected():
            raise DatabaseError("Потеряна связь с базой данных")

        cursor = self._conn.cursor()
        try:
            yield cursor
            self._conn.commit()
        except Exception:
            self._safe_rollback()
            raise
        finally:
            cursor.close()
