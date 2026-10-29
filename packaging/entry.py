"""PyInstaller entry point for the packaged CoCreate app.

Serves the web UI on a free localhost port and shows it in a native
window (pywebview / WKWebView on macOS). Falls back to opening the
default browser if the window toolkit isn't available.
"""

import os
import sys

# Vendored + app packages live at the bundle root.
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))

HOST = "127.0.0.1"
PREFERRED_PORT = 8745


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

    # Blocks on the main thread until the window is closed; daemon
    # threads (the server) die with the process.
    webview.create_window("CoCreate", url, width=1280, height=820,
                          min_size=(900, 600))
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
