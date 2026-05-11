from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from constants import BACKUP_DIR_NAME
from state import STATE


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False



def unique_backup_path(backup_root: Path, relative_path: Path) -> Path:
    candidate = backup_root / relative_path
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    parent = candidate.parent
    counter = 1
    while True:
        next_candidate = parent / f"{stem}_{counter}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        counter += 1


def move_duplicates(keep_id: str, remove_ids: list[str]) -> dict[str, Any]:
    with STATE.lock:
        if STATE.directory is None:
            raise ValueError("No hay un escaneo activo")
        base_dir = STATE.directory.resolve()
        files_by_id = dict(STATE.files_by_id)

    if keep_id not in files_by_id:
        raise ValueError("El archivo a conservar no existe en el escaneo actual")

    keep_path = files_by_id[keep_id].path.resolve()
    if not is_inside(keep_path, base_dir):
        raise ValueError("La ruta a conservar esta fuera del directorio escaneado")

    backup_root = base_dir / BACKUP_DIR_NAME
    moved: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for file_id in remove_ids:
        info = files_by_id.get(file_id)
        if info is None:
            errors.append({"id": file_id, "error": "No existe en el escaneo actual"})
            continue

        source = info.path.resolve()
        if source == keep_path:
            errors.append({"id": file_id, "error": "No se puede mover el archivo marcado para conservar"})
            continue
        if not is_inside(source, base_dir):
            errors.append({"id": file_id, "error": "Ruta fuera del directorio escaneado"})
            continue
        if not source.exists():
            errors.append({"id": file_id, "error": "El archivo ya no existe"})
            continue

        relative = source.relative_to(base_dir)
        destination = unique_backup_path(backup_root, relative)
        try:
            shutil.move(str(source), str(destination))
            moved.append({"from": str(source), "to": str(destination)})
        except OSError as exc:
            errors.append({"id": file_id, "error": str(exc)})

    return {"moved": moved, "errors": errors, "backup": str(backup_root)}


def move_selected_files(remove_ids: list[str]) -> dict[str, Any]:
    with STATE.lock:
        if STATE.directory is None:
            raise ValueError("No hay un escaneo activo")
        base_dir = STATE.directory.resolve()
        files_by_id = dict(STATE.files_by_id)

    backup_root = base_dir / BACKUP_DIR_NAME
    moved: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()

    for file_id in remove_ids:
        if file_id in seen:
            continue
        seen.add(file_id)
        info = files_by_id.get(file_id)
        if info is None:
            errors.append({"id": file_id, "error": "No existe en el escaneo actual"})
            continue

        source = info.path.resolve()
        if not is_inside(source, base_dir):
            errors.append({"id": file_id, "error": "Ruta fuera del directorio escaneado"})
            continue
        if not source.exists():
            errors.append({"id": file_id, "error": "El archivo ya no existe"})
            continue

        relative = source.relative_to(base_dir)
        destination = unique_backup_path(backup_root, relative)
        try:
            shutil.move(str(source), str(destination))
            moved.append({"from": str(source), "to": str(destination)})
        except OSError as exc:
            errors.append({"id": file_id, "error": str(exc)})

    return {"moved": moved, "errors": errors, "backup": str(backup_root)}

