import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_FILE = BASE_DIR / "app.py"


def find_cloudflared() -> str | None:
    env_path = os.getenv("CLOUDFLARED_PATH", "").strip()
    if env_path and os.path.exists(env_path):
        return env_path

    for candidate in ["cloudflared", "cloudflared.exe"]:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    fallback = Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
    if fallback.exists():
        return str(fallback)

    return None


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for_app(url: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status < 500
        except Exception:
            time.sleep(1)
    return False


def stop_process(process: subprocess.Popen | None) -> None:
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def start_app_process() -> subprocess.Popen | None:
    if is_port_open(8000):
        print("FastAPI app is already running on port 8000.")
        return None

    print("Starting FastAPI app...")
    return subprocess.Popen(
        [sys.executable, str(APP_FILE)],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )


def start_tunnel_process(cloudflared_path: str) -> tuple[subprocess.Popen, list[str]]:
    print("Starting Cloudflare Tunnel...")
    proc = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", "http://127.0.0.1:8000"],
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip()
            if text:
                lines.append(text)
                print(text)

    threading.Thread(target=_reader, daemon=True).start()
    return proc, lines


if __name__ == "__main__":
    cloudflared_path = find_cloudflared()
    if not cloudflared_path:
        print("Cloudflare Tunnel CLI was not found.")
        print("Install it with:")
        print("winget install --id Cloudflare.cloudflared -e")
        raise SystemExit(1)

    app_process = None
    tunnel_process = None
    tunnel_lines: list[str] = []

    try:
        app_process = start_app_process()
        if app_process is not None and not wait_for_app("http://127.0.0.1:8000/login", timeout=45):
            print("The app did not become ready in time.")
            raise SystemExit(1)

        tunnel_process, tunnel_lines = start_tunnel_process(cloudflared_path)
        print("Cloudflare Tunnel is running. Press Ctrl+C to stop both services.")

        while True:
            if tunnel_process.poll() is not None:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping services...")
    finally:
        stop_process(tunnel_process)
        stop_process(app_process)

