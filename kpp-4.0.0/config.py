#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import os
import socket
import subprocess
import configparser
from dataclasses import dataclass

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BASE_DIR, "config.ini")


@dataclass(frozen=True)
class AppConfig:
    platform: str
    my_ip: int
    image_folder: str
    power_off_cmd: str

    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    db_charset: str

    app_version: str
    code_poweroff: str
    prefix_worker: str
    auto_update_ms: int
    reconnect_ms: int

    idle_after_hour: int
    idle_timeout_sec: int
    idle_check_ms: int


FONTS = {
    "title":  ("Play", 36, "bold"),
    "f1":     ("Arial", 20),
    "f2":     ("Arial", 18),
    "f3":     ("Arial", 16),
    "f4":     ("Arial", 14),
    "f1b":    ("Arial", 20, "bold"),
    "f2b":    ("Arial", 18, "bold"),
    "f3b":    ("Arial", 16, "bold"),
    "f4b":    ("Arial", 14, "bold"),
}


def _detect_local_ip_octet(target_host: str, target_port: int = 3306) -> int:
    """
    Определяет последний октет локального IP через таблицу маршрутизации ОС
    по направлению к серверу БД (пакеты в сеть не отправляются).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target_host, target_port))
            local_ip = s.getsockname()[0]
            return int(local_ip.split(".")[-1])
    except Exception:
        pass

    # Резервный вариант (как в исходном main.py)
    try:
        out = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, check=True
        ).stdout.strip()
        if out:
            last_ip = out.split()[-1]
            return int(last_ip.split(".")[-1])
    except Exception:
        pass

    return 0


def load_config(config_path: str = _CONFIG_PATH) -> AppConfig:
    """Загружает конфигурацию из INI-файла с фолбэком на дефолтные значения."""
    parser = configparser.ConfigParser()
    if os.path.exists(config_path):
        parser.read(config_path, encoding="utf-8")

    import sys
    platform = sys.platform
    hostname = socket.gethostname()

    default_host = (
        parser.get("database", "host_dev", fallback="192.168.88.200")
        if hostname == "cybstation"
        else parser.get("database", "host", fallback="192.168.0.10")
    )
    db_port = parser.getint("database", "port", fallback=3306)

    if platform == "linux":
        image_folder = parser.get("paths", "images_linux", fallback=r"/mnt/smb/ПВХ/JPG")
        power_off_cmd = "systemctl poweroff"
        # Можно жестко задать my_ip в config.ini при необходимости, иначе автоопределение
        my_ip = parser.getint("app", "my_ip", fallback=0) or _detect_local_ip_octet(default_host, db_port)
    elif platform == "win32":
        image_folder = parser.get("paths", "images_win", fallback=r"\\synas\work\ПВХ\JPG")
        power_off_cmd = "shutdown -t 00 -S"
        my_ip = parser.getint("app", "my_ip", fallback=99)
    else:
        raise RuntimeError(f"Неподдерживаемая ОС: {platform}")

    return AppConfig(
        platform=platform,
        my_ip=my_ip,
        image_folder=image_folder,
        power_off_cmd=power_off_cmd,
        db_host=default_host,
        db_port=db_port,
        db_user=parser.get("database", "user", fallback="workshop"),
        db_password=parser.get("database", "password", fallback="w0rK5h0p"),
        db_name=parser.get("database", "name", fallback="workshop"),
        db_charset=parser.get("database", "charset", fallback="utf8"),
        app_version=parser.get("app", "version", fallback="v 3.7.0"),
        code_poweroff=parser.get("app", "code_poweroff", fallback="12345"),
        prefix_worker=parser.get("app", "prefix_worker", fallback="2200"),
        auto_update_ms=parser.getint("app", "auto_update_ms", fallback=60_000),
        reconnect_ms=parser.getint("app", "reconnect_ms", fallback=5_000),
        idle_after_hour=parser.getint("idle", "after_hour", fallback=17),
        idle_timeout_sec=parser.getint("idle", "timeout_sec", fallback=3600),
        idle_check_ms=parser.getint("idle", "check_ms", fallback=60_000),
    )
