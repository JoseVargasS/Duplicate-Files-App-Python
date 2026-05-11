from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ImageInfo:
    file_id: str
    path: Path
    size: int
    mtime: float
    width: int = 0
    height: int = 0
    sha256: str | None = None
    visual_hash: int | None = None
    visual_error: str | None = None


class ScanState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.directory: Path | None = None
        self.files_by_id: dict[str, ImageInfo] = {}
        self.groups: list[dict[str, Any]] = []
