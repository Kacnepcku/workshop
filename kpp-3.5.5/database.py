#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

"""
database.py — надёжное соединение с MySQL для kpp 3.5.5.

ConnectionHolder инкапсулирует pymysql-соединение:
  * ping(reconnect=True) перед каждым курсором — обрыв соединения
    (перерыв сети, рестарт mysqld, wait_timeout) восстанавливается сам;
  * контекстный менеджер transaction() — commit/rollback в одном месте;
  * таймауты подключения/чтения из config.

Ранее код приложения работал с «голым» атрибутом conn и падал с
OperationalError(2013/2006) при любом обрыве после успешного коннекта.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

import pymysql

import config


class ConnectionHolder:
    """Обёртка над pymysql.Connection с авто-reconnect."""

    def __init__(self) -> None:
        self._conn: Optional[pymysql.connections.Connection] = None

    # -- жизненный цикл ------------------------------------------------------
    def connect(self) -> None:
        """Открыть (переоткрыть) соединение с параметрами из config."""
        self.close()
        self._conn = pymysql.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            charset=config.DB_CHARSET,
            connect_timeout=config.CONNECT_TIMEOUT_SEC,
            read_timeout=config.READ_TIMEOUT_SEC,
            autocommit=False,
        )

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    # -- доступ к курсору -----------------------------------------------------
    def _ensure_alive(self) -> pymysql.connections.Connection:
        if self._conn is None:
            raise pymysql.err.InterfaceError("Соединение с БД не установлено")
        # ping с reconnect прозрачно восстанавливает оборванное соединение
        self._conn.ping(reconnect=True)
        return self._conn

    @contextmanager
    def cursor(self) -> Iterator[pymysql.cursors.Cursor]:
        """Короткое чтение/запись без явного коммита; курсор всегда закрыт."""
        cur = self._ensure_alive().cursor()
        try:
            yield cur
        finally:
            cur.close()

    @contextmanager
    def transaction(self) -> Iterator[pymysql.cursors.Cursor]:
        """Транзакция: commit при успехе, rollback при любом исключении."""
        conn = self._ensure_alive()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()
