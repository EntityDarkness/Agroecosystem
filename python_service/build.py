"""Сборка sidecar для Tauri.

PyInstaller не кросс-компилирует: Windows-бинарник собирается на Windows,
Linux-бинарник — на Linux. Имя файла — target triple, который ждёт Tauri 2:

  python_service-x86_64-pc-windows-msvc.exe
  python_service-x86_64-unknown-linux-gnu

Запуск на целевой ОС из каталога python_service:

  python build.py
  python build.py --target windows
  python build.py --target linux
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

HOST_TRIPLES = {
    ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("Windows", "amd64"): "x86_64-pc-windows-msvc",
    ("Windows", "aarch64"): "aarch64-pc-windows-msvc",
    ("Windows", "arm64"): "aarch64-pc-windows-msvc",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "amd64"): "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("Linux", "arm64"): "aarch64-unknown-linux-gnu",
}

TARGET_OS = {
    "windows": "Windows",
    "linux": "Linux",
}


def host_triple() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    triple = HOST_TRIPLES.get((system, machine))
    if triple is None:
        raise SystemExit(f"Нет target triple для {system} {machine}")
    return triple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Собрать python_service sidecar")
    parser.add_argument("--target", choices=("windows", "linux", "host"), default="host")
    return parser.parse_args()


def patch_scipy_freeze_bug() -> tuple[Path, str] | None:
    """PyInstaller ломает `del obj` в scipy.stats._distn_infrastructure.

    На время сборки подменяем этот фрагмент и возвращаем файл обратно.
    """
    try:
        import scipy.stats as stats
    except ImportError:
        return None
    path = Path(stats.__file__).resolve().parent / "_distn_infrastructure.py"
    if not path.exists():
        return None
    original = path.read_text(encoding="utf-8")
    old = (
        "for obj in [s for s in dir() if s.startswith('_doc_')]:\n"
        "    exec('del ' + obj)\n"
        "del obj\n"
    )
    new = (
        "for obj in [s for s in list(globals()) if s.startswith('_doc_')]:\n"
        "    globals().pop(obj, None)\n"
    )
    if old not in original:
        print("scipy patch anchor не найден, сборка пойдёт без патча", flush=True)
        return None
    path.write_text(original.replace(old, new, 1), encoding="utf-8")
    cache = path.parent / "__pycache__"
    for pyc in cache.glob("_distn_infrastructure*.pyc"):
        pyc.unlink()
    return path, original


def main() -> None:
    args = parse_args()
    system = platform.system()
    triple = host_triple()
    if args.target != "host":
        wanted = TARGET_OS[args.target]
        if system != wanted:
            raise SystemExit(
                f"PyInstaller не кросс-компилирует. Сейчас {system}, запрошен {args.target}. "
                f"Запусти `python build.py --target {args.target}` на машине {wanted}."
            )

    suffix = ".exe" if system == "Windows" else ""
    name = f"python_service-{triple}"
    dist = ROOT / "dist"
    work = ROOT / "build"
    entry = ROOT / "service" / "__main__.py"
    data = ROOT / "data"
    if not (data / "panel_monthly.csv").exists() or not (data / "models").exists():
        raise SystemExit(f"Нет data/panel_monthly.csv или data/models в {ROOT}")

    add_data = f"{data}{os.pathsep}data"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--noupx",
        "--name",
        name,
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        "--paths",
        str(ROOT),
        "--collect-all",
        "catboost",
        "--collect-all",
        "sklearn",
        "--collect-all",
        "scipy",
        "--hidden-import",
        "scipy._cyutility",
        "--collect-all",
        "uvicorn",
        "--collect-submodules",
        "service",
        "--hidden-import",
        "service.main",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--add-data",
        add_data,
        str(entry),
    ]
    print(" ".join(cmd), flush=True)
    patched = patch_scipy_freeze_bug()
    try:
        subprocess.run(cmd, cwd=ROOT, check=True)
    finally:
        if patched is not None:
            path, original = patched
            path.write_text(original, encoding="utf-8")
    artifact = dist / f"{name}{suffix}"
    if not artifact.exists():
        raise SystemExit(f"PyInstaller не создал {artifact}")
    print(f"sidecar: {artifact} ({artifact.stat().st_size} bytes)", flush=True)
    print(
        "Tauri 2: скопируй файл в src-tauri/binaries/ и в tauri.conf.json укажи "
        '"bundle": {"externalBin": ["binaries/python_service"]}',
        flush=True,
    )


if __name__ == "__main__":
    main()
