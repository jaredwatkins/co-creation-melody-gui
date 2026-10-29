"""PyInstaller entry point for the packaged CoCreate app.

Serves the web UI on a free localhost port and shows it in a native
window (pywebview / WKWebView on macOS). Falls back to opening the
default browser if the window toolkit isn't available.

Lifecycle: one instance at a time — a second launch terminates the
first — and closing the window exits the process (server included),
so the app never lingers windowless in the Dock.
"""

import os
import signal
import sys

# Vendored + app packages live at the bundle root.
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))

HOST = "127.0.0.1"
PREFERRED_PORT = 8745
LOCK = os.path.expanduser("~/.cocreate/cocreate.lock")


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


def _take_single_instance() -> None:
    """Terminate a previous instance, then record this one as the owner."""
    try:
        with open(LOCK) as fh:
            old_pid = int(fh.read().strip())
    except (OSError, ValueError):
        old_pid = None
    if old_pid and old_pid != os.getpid() and _pid_alive(old_pid):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(old_pid, sig)
            except OSError:
                break
            for _ in range(20):
                import time

                time.sleep(0.05)
                if not _pid_alive(old_pid):
                    break
            else:
                continue
            break
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


def _run_native() -> None:
    import threading

    import uvicorn
    import webview

    from cocreation.engine import DEFAULT_MODEL_ID, ModelEngine
    from cocreation.server import create_app

    _take_single_instance()

    port = _free_port()
    url = f"http://{HOST}:{port}"
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

    # Blocks on the main thread until the window is closed; closing also
    # exits the process so the server thread and Dock icon never linger.
    window = webview.create_window("CoCreate", url, width=1280, height=820,
                                   min_size=(900, 600), js_api=_SaveApi())
    window.events.closed += lambda: os._exit(0)
    webview.start()


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
