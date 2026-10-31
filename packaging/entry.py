"""PyInstaller entry point for the packaged CoCreate app.

Serves the web UI on a free localhost port and shows it in a native
window (pywebview / WKWebView on macOS). Falls back to opening the
default browser if the window toolkit isn't available.

Lifecycle: one instance at a time — a second launch defers to the
running app and exits — and closing the window exits the process
(server included), so the app never lingers windowless in the Dock.

Startup order matters: the window opens immediately with a loading
screen, while the heavier imports (torch/transformers) and the server
come up in a worker thread. That way a slow first boot still shows
something in seconds, and impatient re-clicks can't kill a mid-boot
instance.
"""

import os
import sys

# Vendored + app packages live at the bundle root.
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))

HOST = "127.0.0.1"
PREFERRED_PORT = 8745
LOCK = os.path.expanduser("~/.cocreate/cocreate.lock")

_LOADING_HTML = """
<!doctype html><html><body style="margin:0;height:100vh;display:flex;
align-items:center;justify-content:center;background:#14161c;color:#cfd3e1;
font-family:-apple-system,Helvetica,sans-serif">
<div style="text-align:center">
  <div style="font-size:28px;font-weight:600;letter-spacing:.5px">CoCreate</div>
  <div style="margin-top:10px;font-size:14px;color:#8b90a3">
    starting up&hellip; first launch can take a minute
  </div>
</div></body></html>
"""


class _SaveApi:
    """Exposed to the page as window.pywebview.api — the native window has no
    browser download machinery, so exports write into ~/Downloads."""

    def save_file(self, filename: str, b64: str) -> str:
        import base64

        data = base64.b64decode(b64)
        outdir = os.path.expanduser("~/Downloads")
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, os.path.basename(filename) or "export")
        root, ext = os.path.splitext(path)
        i = 1
        while os.path.exists(path):
            path = f"{root}-{i}{ext}"
            i += 1
        with open(path, "wb") as fh:
            fh.write(data)
        return path


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_our_app(pid: int) -> bool:
    """True when the pid is a CoCreate process — so a stale lock pointing at a
    recycled pid can't make us mistake an unrelated process for the app."""
    import subprocess

    try:
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
        return "CoCreate" in out.stdout or "cocreate" in out.stdout
    except Exception:
        return False


def _single_instance_or_exit() -> None:
    """If another CoCreate instance is alive, let it win and exit quietly.

    macOS activates the already-running app on `open`/Dock clicks, so the
    existing window stays in front — relaunching never restarts anything.
    """
    try:
        with open(LOCK) as fh:
            old_pid = int(fh.read().strip())
    except (OSError, ValueError):
        old_pid = None
    if (old_pid and old_pid != os.getpid() and _pid_alive(old_pid)
            and _is_our_app(old_pid)):
        os._exit(0)
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "w") as fh:
        fh.write(str(os.getpid()))


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        try:
            s.bind((HOST, PREFERRED_PORT))
            return PREFERRED_PORT
        except OSError:
            s.bind((HOST, 0))
            return s.getsockname()[1]


def _wait_ready(port: int, tries: int = 600) -> None:
    import socket
    import time

    for _ in range(tries):
        try:
            with socket.create_connection((HOST, port), 0.5):
                return
        except OSError:
            time.sleep(0.1)


def _serve(window, port: int) -> None:
    """Runs inside webview.start's worker thread: imports the app stack,
    starts uvicorn, then points the already-visible window at the UI."""
    import threading

    import uvicorn

    try:
        from cocreation.engine import DEFAULT_MODEL_ID, ModelEngine
        from cocreation.server import create_app

        app = create_app(engine=ModelEngine(model_id=DEFAULT_MODEL_ID))
        threading.Thread(
            target=uvicorn.run,
            kwargs={
                "app": app,
                "host": HOST,
                "port": port,
                "log_level": "warning",
                "log_config": None,
            },
            daemon=True,
        ).start()
        _wait_ready(port)
        window.load_url(f"http://{HOST}:{port}")
    except Exception as exc:
        window.load_html(
            "<h1 style='font-family:sans-serif;padding:2em'>"
            f"CoCreate failed to start: {exc}</h1>")


def _run_native() -> None:
    import webview

    _single_instance_or_exit()

    port = _free_port()

    # Window opens first with a loading page; webview.start(func, arg)
    # runs _serve on a worker thread — it brings the server up and then
    # swaps the loading page for the real UI.
    window = webview.create_window(
        "CoCreate", html=_LOADING_HTML, width=1280, height=820,
        min_size=(900, 600), js_api=_SaveApi())
    window.events.closed += lambda: os._exit(0)
    webview.start(_serve, (window, port))


if __name__ == "__main__":
    try:
        _run_native()
    except Exception:
        # Window toolkit unavailable or failed — log the reason, then
        # fall back to serving the UI in the default browser.
        import datetime
        import traceback

        try:
            logdir = os.path.expanduser("~/Library/Logs")
            os.makedirs(logdir, exist_ok=True)
            with open(os.path.join(logdir, "CoCreate-launch.log"), "a") as fh:
                fh.write(f"{datetime.datetime.now().isoformat()}\n")
                traceback.print_exc(file=fh)
                fh.write("\n")
        except OSError:
            pass

        from cocreation.server import main

        main()
