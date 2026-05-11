from __future__ import annotations

import hashlib
import html
import io
import mimetypes
import os
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from constants import BACKUP_DIR_NAME, DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS, VIDEO_EXTENSIONS
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
    if not is_image_file(left.path) or not is_image_file(right.path):
        return None

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


def visual_bucket(info: ImageInfo) -> int:
    if not info.width or not info.height:
        return 0
    return round((info.width / max(info.height, 1)) * 20)


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


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def is_document_file(path: Path) -> bool:
    return path.suffix.lower() in DOCUMENT_EXTENSIONS


def file_kind(path: Path) -> str:
    if is_image_file(path):
        return "imagen"
    if is_video_file(path):
        return "video"
    if is_document_file(path):
        return "documento"
    return "archivo"


def get_supported_files(
    directory: Path,
    limit: int = 0,
    include_images: bool = True,
    include_videos: bool = False,
    include_documents: bool = False,
) -> list[Path]:
    found: list[Path] = []
    enabled_extensions: set[str] = set()
    if include_images:
        enabled_extensions.update(IMAGE_EXTENSIONS)
    if include_videos:
        enabled_extensions.update(VIDEO_EXTENSIONS)
    if include_documents:
        enabled_extensions.update(DOCUMENT_EXTENSIONS)
    if not enabled_extensions:
        return found

    for root, dirs, files in os.walk(directory):
        dirs[:] = [dirname for dirname in dirs if dirname != BACKUP_DIR_NAME]
        for filename in files:
            path = Path(root) / filename
            if path.suffix.lower() in enabled_extensions:
                found.append(path)
                if limit and len(found) >= limit:
                    return found
    return found


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
    if not is_image_file(path) or Image is None or ImageOps is None:
        return 0, 0
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            return int(image.width), int(image.height)
    except Exception:
        return 0, 0


def low_quality_reason(info: ImageInfo) -> str | None:
    if not is_image_file(info.path):
        return None
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
    sampled_rows = 0
    text_like_rows = 0
    step_x = max(1, width // 180)
    step_y = max(1, (y_end - y_start) // 48)

    for y in range(y_start, max(y_start + 1, y_end - 1), step_y):
        sampled_rows += 1
        transitions = 0
        dark_pixels = 0
        light_pixels = 0
        row_total = 0
        for x in range(1, max(2, width - 1), step_x):
            value = int(pixels[x, y])
            left = int(pixels[x - 1, y])
            row_total += 1
            if abs(value - left) > 96:
                transitions += 1
            if value < 48:
                dark_pixels += 1
            elif value > 208:
                light_pixels += 1

        if not row_total:
            continue

        transition_ratio = transitions / row_total
        dark_ratio = dark_pixels / row_total
        light_ratio = light_pixels / row_total

        # Texto superpuesto suele alternar pixeles claros/oscuros en varias filas.
        # Fotos normales tambien tienen bordes, pero rara vez sostienen este patron.
        if 0.08 <= transition_ratio <= 0.34 and dark_ratio >= 0.04 and light_ratio >= 0.04:
            text_like_rows += 1

    if not sampled_rows:
        return 0.0

    return text_like_rows / sampled_rows


def ocr_text_reason(path: Path) -> str | None:
    try:
        import pytesseract  # type: ignore
    except Exception:
        return None

    if Image is None or ImageOps is None:
        return None

    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1200, 1200))
            text = pytesseract.image_to_string(image, config="--psm 6")
    except Exception:
        return None

    normalized = "".join(char for char in text if char.isalnum())
    if len(normalized) >= 10:
        return "posible meme por texto OCR"
    return None


def meme_reason(info: ImageInfo) -> str | None:
    if not is_image_file(info.path):
        return None
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

    ocr_reason = ocr_text_reason(info.path)
    if ocr_reason:
        return ocr_reason

    if Image is None or ImageOps is None or not info.width or not info.height:
        return None

    try:
        with Image.open(info.path) as image:
            image = ImageOps.exif_transpose(image).convert("L")
            image.thumbnail((384, 384))
            width, height = image.size
            if width < 140 or height < 140:
                return None
            band_height = max(28, height // 5)
            bands = (
                (0, band_height),
                (height - band_height, height),
            )
            scores = [text_overlay_score(image, start, end) for start, end in bands]
            if max(scores) >= 0.42:
                return "posible meme por franja de texto"
    except Exception:
        return None

    return None


def build_image_info(files: list[Path], include_visual: bool, include_image_review: bool) -> list[ImageInfo]:
    infos: list[ImageInfo] = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue

        visual_hash = None
        average_hash = None
        visual_error = None
        width, height = (0, 0)
        should_analyze_image = is_image_file(path) and (include_visual or include_image_review)
        if should_analyze_image:
            width, height = read_image_dimensions(path)
        if include_visual and is_image_file(path):
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
    include_images: bool = True,
    include_videos: bool = False,
    include_documents: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, ImageInfo], dict[str, Any]]:
    file_paths = get_supported_files(
        directory,
        limit=limit,
        include_images=include_images,
        include_videos=include_videos,
        include_documents=include_documents,
    )
    infos = build_image_info(
        file_paths,
        include_visual=include_visual,
        include_image_review=include_memes or include_low_quality,
    )
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
    visual_comparisons = 0
    visual_limited = False
    if include_visual:
        visual_infos = [
            info
            for info in info_by_id.values()
            if info.visual_hash is not None or info.average_hash is not None
        ]
        visual_groups: dict[int, list[ImageInfo]] = defaultdict(list)
        for info in visual_infos:
            visual_groups[visual_bucket(info)].append(info)

        max_visual_comparisons = 350_000
        seen_pairs: set[frozenset[str]] = set()
        for bucket, bucket_infos in visual_groups.items():
            candidates: list[ImageInfo] = []
            for nearby_bucket in (bucket - 1, bucket, bucket + 1):
                candidates.extend(visual_groups.get(nearby_bucket, []))

            for left in bucket_infos:
                for right in candidates:
                    if left.file_id >= right.file_id:
                        continue
                    pair_key = frozenset((left.file_id, right.file_id))
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)
                    visual_comparisons += 1
                    if visual_comparisons > max_visual_comparisons:
                        visual_limited = True
                        break
                    reason = visual_match_reason(left, right, visual_threshold)
                    if reason:
                        uf.union(left.file_id, right.file_id)
                        reasons[pair_key].add(reason)
                        visual_pairs += 1
                if visual_limited:
                    break
            if visual_limited:
                break

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
        "scanned": len(file_paths),
        "readable": len(infos),
        "groups": sum(1 for group in groups if group.get("kind") == "duplicate"),
        "review_groups": len(review_groups),
        "to_remove": sum(len(group["files"]) - 1 for group in groups if group.get("kind") == "duplicate"),
        "review_candidates": sum(len(group["files"]) for group in review_groups),
        "visual_available": Image is not None,
        "visual_pairs": visual_pairs,
        "visual_comparisons": visual_comparisons,
        "visual_limited": visual_limited,
        "supported_images": sum(1 for info in infos if is_image_file(info.path)),
        "supported_videos": sum(1 for info in infos if is_video_file(info.path)),
        "supported_documents": sum(1 for info in infos if is_document_file(info.path)),
        "include_images": include_images,
        "include_videos": include_videos,
        "include_documents": include_documents,
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
        "kind": file_kind(info.path),
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
    if is_video_file(path):
        video_thumb = make_video_thumbnail(path, max_size=max_size)
        if video_thumb is not None:
            return video_thumb, "image/jpeg"
        return make_file_placeholder(path, detail="Instala ffmpeg para ver miniatura real"), "image/svg+xml"

    if is_document_file(path):
        document_thumb = make_document_thumbnail(path, max_size=max_size)
        if document_thumb is not None:
            return document_thumb, "image/jpeg"
        if path.suffix.lower() == ".pdf":
            return make_file_placeholder(path, detail="Instala PyMuPDF: npm run setup"), "image/svg+xml"
        return make_file_placeholder(path), "image/svg+xml"

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


def make_video_thumbnail(path: Path, max_size: int = 360) -> bytes | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
        output_path = Path(temp_file.name)

    try:
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "1",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale='min({max_size},iw)':-2",
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, timeout=12, check=False)
        if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            return None

        if Image is not None and ImageOps is not None:
            with Image.open(output_path) as image:
                image.thumbnail((max_size, max_size))
                image = image.convert("RGB")
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=84, optimize=True)
                return output.getvalue()

        return output_path.read_bytes()
    except Exception:
        return None
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def make_document_thumbnail(path: Path, max_size: int = 360) -> bytes | None:
    if path.suffix.lower() == ".pdf":
        pdf_thumb = make_pdf_thumbnail(path, max_size=max_size)
        if pdf_thumb is not None:
            return pdf_thumb
    return None


def make_pdf_thumbnail(path: Path, max_size: int = 360) -> bytes | None:
    try:
        import fitz  # type: ignore

        document = fitz.open(path)
        try:
            if document.page_count < 1:
                return None
            page = document.load_page(0)
            scale = max_size / max(page.rect.width, page.rect.height)
            scale = max(scale, 0.25)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image_bytes = pixmap.tobytes("png")
        finally:
            document.close()

        if Image is None:
            return image_bytes
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.thumbnail((max_size, max_size))
            image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=84, optimize=True)
            return output.getvalue()
    except Exception:
        pass

    if Image is None or ImageOps is None:
        return None

    try:
        with Image.open(path) as image:
            image.seek(0)
            image.thumbnail((max_size, max_size))
            image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=84, optimize=True)
            return output.getvalue()
    except Exception:
        return None


def make_file_placeholder(path: Path, detail: str = "") -> bytes:
    kind = file_kind(path)
    ext = path.suffix.upper().lstrip(".") or "FILE"
    color = {
        "video": "#3b82f6",
        "documento": "#f59e0b",
    }.get(kind, "#64748b")
    label = html.escape(kind.upper())
    ext_label = html.escape(ext[:8])
    name = html.escape(path.name[:42])
    detail_text = html.escape(detail or "miniatura no disponible")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="360" height="240" viewBox="0 0 360 240">
  <rect width="360" height="240" fill="#0c1015"/>
  <rect x="92" y="36" width="176" height="132" rx="10" fill="#121820" stroke="{color}" stroke-width="3"/>
  <text x="180" y="92" text-anchor="middle" font-family="Segoe UI, Arial" font-size="22" font-weight="700" fill="{color}">{ext_label}</text>
  <text x="180" y="126" text-anchor="middle" font-family="Segoe UI, Arial" font-size="16" fill="#f2f5f8">{label}</text>
  <text x="180" y="154" text-anchor="middle" font-family="Segoe UI, Arial" font-size="11" fill="#a8b3c2">{detail_text}</text>
  <text x="180" y="204" text-anchor="middle" font-family="Segoe UI, Arial" font-size="13" fill="#a8b3c2">{name}</text>
</svg>"""
    return svg.encode("utf-8")
