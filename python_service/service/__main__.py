"""Точка входа sidecar.

Tauri спавнит этот процесс и убивает его (start/stop = spawn/kill).
Сервер слушает только localhost.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def seed_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "data"
    return Path(__file__).resolve().parents[1] / "data"


def default_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return seed_dir()


def ensure_data(data: Path) -> None:
    """Сид из бандла копируется рядом с exe. Панель и модели после этого пишутся туда."""
    seed = seed_dir()
    data.mkdir(parents=True, exist_ok=True)
    if seed.resolve() == data.resolve():
        return
    for name in ("models", "raw", "panel_monthly.csv"):
        src = seed / name
        dst = data / name
        if not src.exists() or dst.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python_service")
    parser.add_argument("command", nargs="?", choices=("start", "stop"), default="start")
    parser.add_argument("--host", default=os.environ.get("WTP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WTP_PORT", "8000")))
    parser.add_argument("--data-dir", default=os.environ.get("WTP_DATA_DIR"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "stop":
        return

    data = Path(args.data_dir) if args.data_dir else default_data_dir()
    ensure_data(data)
    os.environ["WTP_DATA_DIR"] = str(data.resolve())

    import uvicorn

    from service.main import app

    print(
        f"python_service http://{args.host}:{args.port} data={data.resolve()}",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
