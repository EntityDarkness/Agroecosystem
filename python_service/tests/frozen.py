"""Проверка собранного sidecar через настоящий HTTP и новый каталог данных."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def main():
    binary = Path(sys.argv[1]).resolve()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = "frozen-smoke-local-token"
    environment = {**os.environ, "WTP_API_TOKEN": token}
    with tempfile.TemporaryDirectory(prefix="wtp-frozen-") as work:
        log_path = Path(work) / "service.log"
        with log_path.open("wb") as log:
            child = subprocess.Popen([str(binary), "--host", "127.0.0.1", "--port", str(port), "--data-dir", str(Path(work) / "data")],
                env=environment, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                def request(path, body=None, authenticated=True):
                    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                        data=None if body is None else json.dumps(body).encode(),
                        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if authenticated else {})})
                    with urllib.request.urlopen(req, timeout=120) as response:
                        return json.load(response)

                deadline = time.monotonic() + 180
                while True:
                    if child.poll() is not None:
                        raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace"))
                    try:
                        assert request("/health")["status"] == "ok"
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() > deadline:
                            raise RuntimeError("Sidecar startup timeout: " + log_path.read_text(encoding="utf-8", errors="replace"))
                        time.sleep(0.5)
                assert len(request("/meta")["input_fields"]) == 49
                assert len(request("/predict/indicators", {})["indicators"]) == 8
                assert len(request("/predict/sediments", {})["sediments"]) == 14
                assert "achieved" in request("/predict/dosing", {})
                try:
                    request("/health", authenticated=False)
                    raise AssertionError("Unauthenticated request succeeded")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 401
                print("Frozen sidecar: startup, schema, 8 indicators, 14 sediments, dosing, auth OK")
            finally:
                if os.name == "nt" and child.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                elif child.poll() is None:
                    child.terminate()
                child.wait(timeout=15)


if __name__ == "__main__":
    main()
