#!/usr/bin/env -S python3
# -*- coding: utf-8 -*-

import sys
import tkinter as tk
from config import load_config
from database.connection import Database
from database.repository import WorkshopRepository
from services.worker_service import WorkerService
from services.detal_service import DetalService
from ui.app import Application


def main():
    try:
        cfg = load_config()
    except RuntimeError as e:
        print(f"Ошибка запуска: {e}")
        sys.exit(1)

    db = Database(cfg)
    repo = WorkshopRepository()
    worker_service = WorkerService(db, repo, cfg)
    detal_service = DetalService(db, repo)

    root = tk.Tk()
    Application(
        root=root,
        cfg=cfg,
        db=db,
        worker_service=worker_service,
        detal_service=detal_service,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
