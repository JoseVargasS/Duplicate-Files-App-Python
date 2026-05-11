from __future__ import annotations

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from constants import DEFAULT_PORT, HOST
from file_actions import move_duplicates, move_selected_files
from image_tools import Image, find_duplicate_groups, make_thumbnail
from state import STATE

WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_HTML = WEB_DIR / "index.html"


def load_index_html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(
    handler: BaseHTTPRequestHandler,
    body: str,
    status: int = 200,
    content_type: str = "text/plain; charset=utf-8",
) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))



class DuplicateImageHandler(BaseHTTPRequestHandler):
    server_version = "DuplicateImageApp/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            text_response(self, load_index_html(), content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/api/image":
            self.handle_image(parsed.query)
            return
        json_response(self, {"error": "Ruta no encontrada"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/choose-folder":
                self.handle_choose_folder()
            elif parsed.path == "/api/scan":
                self.handle_scan()
            elif parsed.path == "/api/move":
                self.handle_move()
            elif parsed.path == "/api/move-selected":
                self.handle_move_selected()
            else:
                json_response(self, {"error": "Ruta no encontrada"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def handle_choose_folder(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:
            json_response(self, {"error": f"No se pudo abrir selector de carpetas: {exc}"}, status=500)
            return

        selected: dict[str, str] = {"path": ""}

        def pick() -> None:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected["path"] = filedialog.askdirectory(title="Selecciona la carpeta de imagenes")
            root.destroy()

        thread = threading.Thread(target=pick)
        thread.start()
        thread.join()
        json_response(self, {"directory": selected["path"]})

    def handle_scan(self) -> None:
        payload = read_json(self)
        directory = Path(str(payload.get("directory", "")).strip()).expanduser()
        if not directory.exists() or not directory.is_dir():
            raise ValueError("Selecciona una carpeta valida")

        limit = int(payload.get("limit") or 0)
        include_visual = bool(payload.get("include_visual", True))
        include_memes = bool(payload.get("include_memes", False))
        include_low_quality = bool(payload.get("include_low_quality", False))
        visual_threshold = int(payload.get("visual_threshold") or 6)
        visual_threshold = max(0, min(20, visual_threshold))

        groups, files_by_id, metadata = find_duplicate_groups(
            directory=directory,
            limit=limit,
            include_visual=include_visual,
            visual_threshold=visual_threshold,
            include_memes=include_memes,
            include_low_quality=include_low_quality,
        )

        with STATE.lock:
            STATE.directory = directory.resolve()
            STATE.files_by_id = files_by_id
            STATE.groups = groups

        json_response(self, {"groups": groups, "metadata": metadata})

    def handle_move(self) -> None:
        payload = read_json(self)
        keep_id = str(payload.get("keep_id", ""))
        remove_ids = [str(item) for item in payload.get("remove_ids", [])]
        if not keep_id or not remove_ids:
            raise ValueError("Selecciona que conservar y al menos un archivo para mover")
        result = move_duplicates(keep_id, remove_ids)
        json_response(self, result)

    def handle_move_selected(self) -> None:
        payload = read_json(self)
        remove_ids = [str(item) for item in payload.get("remove_ids", [])]
        if not remove_ids:
            raise ValueError("Selecciona al menos un archivo para mover")
        result = move_selected_files(remove_ids)
        json_response(self, result)

    def handle_image(self, query: str) -> None:
        params = parse_qs(query)
        file_id = params.get("id", [""])[0]
        with STATE.lock:
            info = STATE.files_by_id.get(file_id)

        if info is None:
            self.send_error(HTTPStatus.NOT_FOUND, "Imagen no encontrada")
            return

        try:
            data, mime = make_thumbnail(info.path)
        except Exception:
            self.send_error(HTTPStatus.NOT_FOUND, "No se pudo cargar la imagen")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)



def find_free_port(start_port: int) -> int:
    import socket

    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError("No se encontro un puerto libre")


def run_server(port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    selected_port = find_free_port(port)
    server = ThreadingHTTPServer((HOST, selected_port), DuplicateImageHandler)
    url = f"http://{HOST}:{selected_port}"

    print(f"Servidor iniciado en {url}")
    print("Presiona Ctrl+C para cerrar.")
    if Image is None:
        print("Aviso: Pillow no esta instalado. Instala con: pip install pillow")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando servidor...")
    finally:
        server.server_close()
