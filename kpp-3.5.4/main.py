#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import tkinter as tk
from datetime import datetime
from app import Application

# Шрифты Tk ===================================================================================
font0  = ("Play", 36, "bold")   # название рабочего места
font1  = ("Arial", 20)
font2  = ("Arial", 18)
font3  = ("Arial", 16)
font4  = ("Arial", 14)
font1b = ("Arial", 20, "bold")
font2b = ("Arial", 18, "bold")
font3b = ("Arial", 16, "bold")
font4b = ("Arial", 14, "bold")

# Определение ОС и путей ========================================================================
if sys.platform == 'linux':
    LOG_FILE     = 'work.log'
    image_folder = r"/mnt/smb/ПВХ/JPG"
    power_off    = "systemctl poweroff"
    MY_IP        = subprocess.run(
                        "hostname -I | awk -F'.' '{print $NF}'",
                        shell=True, capture_output=True, text=True
                        ).stdout.strip()
elif sys.platform == 'win32':
    LOG_FILE     = 'test.log'
    image_folder = r"\\synas\work\ПBX\JPG"
    power_off    = "shutdown -t 00 -S"
    MY_IP        = '99'
else:
    sys.exit(0)

# Параметры подключения к БД ====================================================================
if subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip() == "cybstation":
    DB_HOST = "192.168.88.200"
else:
    DB_HOST = "192.168.0.10"
    
DB_USER     = 'workshop'
DB_PASSWORD = 'w0rK5h0p'
DB_NAME     = 'workshop'
DB_CHARSET  = 'utf8'

# Константы приложения ==========================================================================
CODE_POWEROFF  = '12345'    # код сканирования для выключения ПК
PREFIX_WORKER  = '2200'     # префикс штрих-кода сотрудника

GRI_IMPOST     = '3'        # группа «импост» — не регистрируется
GRI_FRAME      = 'r'        # рама
GRI_SASH       = 's'        # створка

AUTO_UPDATE_MS = 60_000     # период автообновления списка сотрудников
RECONNECT_MS   = 5_000      # пауза между попытками подключения к БД

# Логирование ===================================================================================
def log_message(message):
    """Запись сообщения в лог-файл с временной меткой."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Ошибка записи лога: {e}")

def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()

if __name__ == "__main__":
    main()
