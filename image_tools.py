from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from constants import BACKUP_DIR_NAME, IMAGE_EXTENSIONS
from models import ImageInfo

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None


def file_id_for(path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8", errors="ignore")).hexdigest()
    return digest[:16]


def calculate_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def calculate_dhash(path: Path, hash_size: int = 8) -> tuple[int | None, str | None]:
    """Calcula difference hash de 64 bits. Menor distancia = imagen mas parecida."""
    if Image is None or ImageOps is None:
        return None, "Pillow no esta instalado"

    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
    except Exception as exc:
        return None, str(exc)

    bits = 0
    for row in range(hash_size):
        row_start = row * (hash_size + 1)
        for col in range(hash_size):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            bits = (bits << 1) | int(left > right)
    return bits, None


def calculate_average_hash(path: Path, hash_size: int = 16) -> tuple[int | None, str | None]:
    """Calcula average hash. Ayuda con la misma foto en distinto tamano/calidad."""
    if Image is None or ImageOps is None:
        return None, "Pillow no esta instalado"

    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("L").resize((hash_size, hash_size), Image.Resampling.LANCZOS)
            pixels = list(image.getdata())
    except Exception as exc:
        return None, str(exc)

    average = sum(pixels) / len(pixels)
    bits = 0
    for value in pixels:
        bits = (bits << 1) | int(value >= average)
    return bits, None


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def visual_match_reason(left: ImageInfo, right: ImageInfo, visual_threshold: int) -> str | None:
    if left.width and left.height and right.width and right.height:
        left_ratio = left.width / max(left.height, 1)
        right_ratio = right.width / max(right.height, 1)
        if abs(left_ratio - right_ratio) > 0.18:
            return None

    if left.visual_hash is not None and right.visual_hash is not None:
        distance = hamming_distance(left.visual_hash, right.visual_hash)
        if distance <= visual_threshold:
            return f"visual dHash ({distance})"

    if left.average_hash is not None and right.average_hash is not None:
        distance = hamming_distance(left.average_hash, right.average_hash)
        average_threshold = min(72, 18 + visual_threshold * 5)
        if distance <= average_threshold:
            return f"visual aHash ({distance})"

    return None


class UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def get_image_files(directory: Path, limit: int = 0) -> list[Path]:
    images: list[Path] = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [dirname for dirname in dirs if dirname != BACKUP_DIR_NAME]
        for filename in files:
            path = Path(root) / filename
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(path)
                if limit and len(images) >= limit:
                    return images
    return images


def image_quality_score(info: ImageInfo) -> tuple[int, int]:
    """Mayor puntaje = mayor resolucion/calidad util para conservar."""
    return (info.width * info.height, info.size)


def choose_best_quality_oldest(files: list[ImageInfo]) -> ImageInfo:
    """Conserva primero la imagen de mayor calidad; si empata, la mas antigua."""
    return min(
        files,
        key=lambda item: (
            -image_quality_score(item)[0],
            -image_quality_score(item)[1],
            item.mtime,
            str(item.path).lower(),
        ),
    )


def read_image_dimensions(path: Path) -> tuple[int, int]:
    if Image is None or ImageOps is None:
        return 0, 0
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            return int(image.width), int(image.height)
    except Exception:
        return 0, 0


def low_quality_reason(info: ImageInfo) -> str | None:
    pixels = info.width * info.height
    shortest_side = min(info.width, info.height) if info.width and info.height else 0
    if pixels and pixels <= 360_000:
        return f"miniatura o baja resolucion ({info.width}x{info.height})"
    if shortest_side and shortest_side < 480:
        return f"lado muy pequeno ({info.width}x{info.height})"
    name = info.path.name.lower()
    if any(token in name for token in ("thumb", "thumbnail", "miniatura", "preview", "cache")):
        return "nombre de miniatura/cache"
    return None


def text_overlay_score(image: Any, y_start: int, y_end: int) -> float:
    width, height = image.size
    pixels = image.load()
    total = 0
    strong_edges = 0
    very_dark = 0
    very_light = 0
    row_hits: set[int] = set()
    step_x = max(1, width // 220)
    step_y = max(1, (y_end - y_start) // 44)

    for y in range(y_start, max(y_start + 1, y_end - 1), step_y):
        row_edges = 0
        row_total = 0
        for x in range(1, max(2, width - 1), step_x):
            value = int(pixels[x, y])
            left = int(pixels[x - 1, y])
            right = int(pixels[min(width - 1, x + 1), y])
            up = int(pixels[x, max(0, y - 1)])
            down = int(pixels[x, min(height - 1, y + 1)])
            total += 1
            row_total += 1
            if (
                abs(value - left) > 48
                or abs(value - right) > 48
                or abs(value - up) > 48
                or abs(value - down) > 48
            ):
                strong_edges += 1
                row_edges += 1
            if value < 38:
                very_dark += 1
            elif value > 218:
                very_light += 1
        if row_total and row_edges / row_total > 0.16:
            row_hits.add(y)

    if not total:
        return 0.0

    edge_ratio = strong_edges / total
    dark_ratio = very_dark / total
    light_ratio = very_light / total
    row_ratio = len(row_hits) / max(1, (y_end - y_start) // step_y)
    return edge_ratio + min(dark_ratio, light_ratio) * 1.2 + row_ratio * 0.55


def meme_reason(info: ImageInfo) -> str | None:
    name = info.path.name.lower()
    meme_tokens = (
        "meme",
        "memes",
        "funny",
        "joke",
        "chiste",
        "humor",
        "lol",
        "dank",
        "sticker",
        "reaction",
        "caption",
        "quote",
        "frase",
        "texto",
    )
    if any(token in name for token in meme_tokens):
        return "posible meme por nombre"

    if Image is None or ImageOps is None or not info.width or not info.height:
        return None

    try:
        with Image.open(info.path) as image:
            image = ImageOps.exif_transpose(image).convert("L")
            image.thumbnail((256, 256))
            width, height = image.size
            if width < 80 or height < 80:
                return None
            band_height = max(18, height // 4)
            band_scores = []
            for band_index in range(5):
                y_start = int((height - band_height) * (band_index / 4))
                band_scores.append(text_overlay_score(image, y_start, min(height, y_start + band_height)))
            ratio = width / max(height, 1)
            if 0.35 <= ratio <= 3.2 and max(band_scores) > 0.09:
                return "posible meme por texto dentro de la imagen"
    except Exception:
        return None

    return None


def build_image_info(files: list[Path], include_visual: bool) -> list[ImageInfo]:
    infos: list[ImageInfo] = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue

        visual_hash = None
        average_hash = None
        visual_error = None
        width, height = read_image_dimensions(path)
        if include_visual:
            visual_hash, visual_error = calculate_dhash(path)
            average_hash, average_error = calculate_average_hash(path)
            visual_error = visual_error or average_error

        infos.append(
            ImageInfo(
                file_id=file_id_for(path),
                path=path,
                size=stat.st_size,
                mtime=stat.st_mtime,
                width=width,
                height=height,
                visual_hash=visual_hash,
                average_hash=average_hash,
                visual_error=visual_error,
            )
        )
    return infos


def find_duplicate_groups(
    directory: Path,
    limit: int,
    include_visual: bool,
    visual_threshold: int,
    include_memes: bool,
    include_low_quality: bool,
) -> tuple[list[dict[str, Any]], dict[str, ImageInfo], dict[str, Any]]:
    image_paths = get_image_files(directory, limit=limit)
    infos = build_image_info(image_paths, include_visual=include_visual)
    info_by_id = {info.file_id: info for info in infos}
    uf = UnionFind(list(info_by_id))
    reasons: dict[frozenset[str], set[str]] = defaultdict(set)

    size_groups: dict[int, list[ImageInfo]] = defaultdict(list)
    for info in infos:
        size_groups[info.size].append(info)

    for same_size_infos in size_groups.values():
        if len(same_size_infos) < 2:
            continue

        hash_groups: dict[str, list[ImageInfo]] = defaultdict(list)
        for info in same_size_infos:
            digest = calculate_sha256(info.path)
            if digest:
                hash_groups[digest].append(
                    ImageInfo(
                        file_id=info.file_id,
                        path=info.path,
                        size=info.size,
                        mtime=info.mtime,
                        width=info.width,
                        height=info.height,
                        sha256=digest,
                        visual_hash=info.visual_hash,
                        average_hash=info.average_hash,
                        visual_error=info.visual_error,
                    )
                )

        for exact_infos in hash_groups.values():
            if len(exact_infos) < 2:
                continue
            first = exact_infos[0].file_id
            for other in exact_infos[1:]:
                uf.union(first, other.file_id)
                reasons[frozenset((first, other.file_id))].add("exacta")
                info_by_id[other.file_id] = other
            info_by_id[first] = exact_infos[0]

    visual_pairs = 0
    if include_visual:
        visual_infos = [
            info
            for info in info_by_id.values()
            if info.visual_hash is not None or info.average_hash is not None
        ]
        for i, left in enumerate(visual_infos):
            for right in visual_infos[i + 1 :]:
                reason = visual_match_reason(left, right, visual_threshold)
                if reason:
                    uf.union(left.file_id, right.file_id)
                    reasons[frozenset((left.file_id, right.file_id))].add(reason)
                    visual_pairs += 1

    grouped_ids: dict[str, list[str]] = defaultdict(list)
    for file_id in info_by_id:
        grouped_ids[uf.find(file_id)].append(file_id)

    groups: list[dict[str, Any]] = []
    for ids in grouped_ids.values():
        if len(ids) < 2:
            continue
        group_infos = sorted(
            (info_by_id[file_id] for file_id in ids),
            key=lambda item: (-image_quality_score(item)[0], -image_quality_score(item)[1], item.mtime),
        )
        keep = choose_best_quality_oldest(group_infos)
        group_reasons: set[str] = set()
        for i, left_id in enumerate(ids):
            for right_id in ids[i + 1 :]:
                group_reasons.update(reasons.get(frozenset((left_id, right_id)), set()))

        groups.append(
            {
                "group_id": len(groups) + 1,
                "kind": "duplicate",
                "reason": ", ".join(sorted(group_reasons)) or "visual",
                "keep_id": keep.file_id,
                "files": [serialize_info(info, directory) for info in group_infos],
            }
        )

    groups.sort(key=lambda group: group["files"][0]["mtime"])
    for index, group in enumerate(groups, 1):
        group["group_id"] = index

    duplicate_ids = {file["id"] for group in groups for file in group["files"]}
    review_groups = find_review_groups(
        infos=infos,
        directory=directory,
        include_memes=include_memes,
        include_low_quality=include_low_quality,
        duplicate_ids=duplicate_ids,
    )
    for group in review_groups:
        group["group_id"] = len(groups) + 1
        groups.append(group)

    metadata = {
        "scanned": len(image_paths),
        "readable": len(infos),
        "groups": sum(1 for group in groups if group.get("kind") == "duplicate"),
        "review_groups": len(review_groups),
        "to_remove": sum(len(group["files"]) - 1 for group in groups if group.get("kind") == "duplicate"),
        "review_candidates": sum(len(group["files"]) for group in review_groups),
        "visual_available": Image is not None,
        "visual_pairs": visual_pairs,
        "backup_dir_name": BACKUP_DIR_NAME,
    }
    return groups, info_by_id, metadata


def find_review_groups(
    infos: list[ImageInfo],
    directory: Path,
    include_memes: bool,
    include_low_quality: bool,
    duplicate_ids: set[str],
) -> list[dict[str, Any]]:
    review_groups: list[dict[str, Any]] = []
    for info in sorted(infos, key=lambda item: item.mtime):
        if info.file_id in duplicate_ids:
            continue

        reasons: list[str] = []
        if include_memes:
            reason = meme_reason(info)
            if reason:
                reasons.append(reason)
        if include_low_quality:
            reason = low_quality_reason(info)
            if reason:
                reasons.append(reason)

        if not reasons:
            continue

        review_groups.append(
            {
                "group_id": 0,
                "kind": "review",
                "reason": ", ".join(reasons),
                "keep_id": "",
                "files": [serialize_info(info, directory)],
            }
        )
    return review_groups


def serialize_info(info: ImageInfo, base_dir: Path) -> dict[str, Any]:
    try:
        relative = str(info.path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        relative = str(info.path)

    return {
        "id": info.file_id,
        "name": info.path.name,
        "path": str(info.path),
        "relative": relative,
        "size": info.size,
        "size_text": human_size(info.size),
        "width": info.width,
        "height": info.height,
        "dimensions_text": f"{info.width}x{info.height}" if info.width and info.height else "sin dimensiones",
        "quality_score": image_quality_score(info)[0],
        "mtime": info.mtime,
        "mtime_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.mtime)),
        "sha256": info.sha256,
        "visual_error": info.visual_error,
    }


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def make_thumbnail(path: Path, max_size: int = 360) -> tuple[bytes, str]:
    if Image is None or ImageOps is None:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path.read_bytes(), mime

    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((max_size, max_size))
        image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True)
        return output.getvalue(), "image/jpeg"
