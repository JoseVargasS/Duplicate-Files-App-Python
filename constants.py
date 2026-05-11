IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".avif",
    ".heic",
    ".heif",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".m4v",
    ".3gp",
    ".mpeg",
    ".mpg",
}
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".rtf",
    ".csv",
    ".odt",
    ".ods",
    ".odp",
    ".zip",
    ".rar",
    ".7z",
}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | DOCUMENT_EXTENSIONS
BACKUP_DIR_NAME = "_DUPLICADOS_ELIMINADOS"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
