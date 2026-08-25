from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 17373
URL = f"http://{HOST}:{PORT}"


def server_ready(timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def run_server() -> None:
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Monstrum Codex Infinite")
    parser.add_argument("--browser", action="store_true", help="Open the browser UI instead of the desktop shell")
    args = parser.parse_args()

    already_running = server_ready(timeout=0.5)
    if not already_running:
        thread = threading.Thread(target=run_server, daemon=True, name="monstrum-server")
        thread.start()
        if not server_ready():
            raise SystemExit("The local Monstrum Codex server did not start.")
    if args.browser:
        webbrowser.open(URL)
        thread.join()
        return
    try:
        import webview
        webview.create_window(
            "Monstrum Codex Infinite",
            URL,
            width=1500,
            height=960,
            min_size=(1000, 700),
            background_color="#08070d",
        )
        webview.start(private_mode=False)
    except Exception as exc:
        print(f"Desktop shell unavailable ({exc}); opening the browser version.")
        webbrowser.open(URL)
        thread.join()


if __name__ == "__main__":
    main()
