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
                def request(path, body=None, authenticated=True, method=None):
                    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                        data=None if body is None else json.dumps(body).encode(),
                        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if authenticated else {})}, method=method)
                    with urllib.request.urlopen(req, timeout=120) as response:
                        if response.status == 204:
                            return None
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
                assert request("/health")["storage"] == "sqlite"
                assert request("/api/stats/summary")["indicators"] == 49
                point = request("/api/points", {"code": "FROZEN_TEST", "name": "Frozen test point"})
                endpoint = f"/api/points/{point['id']}"
                assert request(endpoint, {"name": "Updated frozen point"}, method="PATCH")["name"] == "Updated frozen point"
                spec = request("/api/indicators", {"code":"FROZEN_EXTRA", "name":"Extra frozen indicator", "unit":"pH", "medium":"water", "point_id":point["id"], "max_value":14})
                catalog = request("/api/workspace")
                assert len(catalog["ml_fields"]) == 49
                snapshot = request("/api/months/2026-10", {"values":{str(spec["id"]):7.0}, "catalog_revision":catalog["revision"]}, method="PATCH")
                measured = next(row for row in snapshot["items"] if row["indicator_id"] == spec["id"])
                assert request(f"/api/series/{spec['id']}")["history"][0]["value"] == 7.0
                assert request(f"/api/measurements/{measured['id']}", method="DELETE") is None
                assert request(f"/api/indicators/{spec['id']}", method="DELETE") is None
                assert request(endpoint, method="DELETE") is None
                assert request("/api/exchange/export?per_page=1")["count"] > 0
                assert len(request("/predict/indicators", {})["indicators"]) == 8
                assert len(request("/predict/sediments", {})["sediments"]) == 14
                assert "achieved" in request("/predict/dosing", {})
                try:
                    request("/health", authenticated=False)
                    raise AssertionError("Unauthenticated request succeeded")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 401
                print("Frozen sidecar: dynamic forms, dictionaries, 49 ML inputs, SQLite CRUD, CSV, forecasts, auth OK")
            finally:
                if os.name == "nt" and child.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                elif child.poll() is None:
                    child.terminate()
                child.wait(timeout=15)


if __name__ == "__main__":
    main()
