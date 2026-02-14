import os
import re
import uuid
from pathlib import Path

from django.core.exceptions import ValidationError

try:
    import magic
except ImportError:  # pragma: no cover
    magic = None

MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

ALLOWED_MIME_BY_EXTENSION = {
    ".pdf": {"application/pdf"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
}

MAGIC_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}

DANGEROUS_INTERMEDIATE_EXTENSIONS = {
    ".php",
    ".phtml",
    ".phar",
    ".cgi",
    ".pl",
    ".py",
    ".sh",
    ".bash",
    ".js",
    ".jar",
    ".exe",
    ".msi",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".dll",
}

SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._ -]{1,255}$")


class UploadValidationError(ValidationError):
    """ValidationError specialisee pour les uploads."""


def _normalize_mime(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _validate_filename(file_name: str) -> tuple[str, list[str]]:
    if not file_name:
        raise UploadValidationError("Nom de fichier invalide.")

    if "\x00" in file_name:
        raise UploadValidationError("Nom de fichier invalide.")

    if "/" in file_name or "\\" in file_name:
        raise UploadValidationError("Nom de fichier invalide.")

    clean_name = os.path.basename(file_name).strip()
    if not clean_name or clean_name.startswith(".") or ".." in clean_name:
        raise UploadValidationError("Nom de fichier invalide.")

    if not SAFE_FILENAME_PATTERN.fullmatch(clean_name):
        raise UploadValidationError("Nom de fichier invalide.")

    suffixes = [suffix.lower() for suffix in Path(clean_name).suffixes]
    if not suffixes:
        raise UploadValidationError(
            "Format de fichier non accepte. Autorises: PDF, JPG, JPEG, PNG."
        )

    final_extension = suffixes[-1]
    if final_extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            "Format de fichier non accepte. Autorises: PDF, JPG, JPEG, PNG."
        )

    if any(ext in DANGEROUS_INTERMEDIATE_EXTENSIONS for ext in suffixes[:-1]):
        raise UploadValidationError("Nom de fichier dangereux detecte.")

    return clean_name, suffixes


def validate_uploaded_file(uploaded_file, max_size_bytes: int = MAX_UPLOAD_SIZE_BYTES) -> dict:
    """
    Valide strictement un fichier uploadé (extension + MIME + signature binaire).

    Retourne un dictionnaire avec des metadonnees utiles si le fichier est valide.
    Le pointeur du fichier est remis a zero avant retour.
    """
    if uploaded_file is None:
        raise UploadValidationError("Aucun fichier recu.")

    clean_name, suffixes = _validate_filename(uploaded_file.name or "")
    extension = suffixes[-1]

    if uploaded_file.size is None or uploaded_file.size <= 0:
        raise UploadValidationError("Fichier vide ou invalide.")

    if uploaded_file.size > max_size_bytes:
        raise UploadValidationError(
            "Le fichier est trop volumineux. Taille maximale autorisee: 5 Mo."
        )

    if magic is None:
        raise UploadValidationError(
            "Validation de signature indisponible sur le serveur."
        )

    # Lire juste le debut du fichier suffit pour la detection MIME/signature.
    head = uploaded_file.read(8192)
    uploaded_file.seek(0)

    if not head:
        raise UploadValidationError("Fichier vide ou invalide.")

    expected_signatures = MAGIC_SIGNATURES[extension]
    if not any(head.startswith(signature) for signature in expected_signatures):
        raise UploadValidationError("Signature binaire invalide pour ce type de fichier.")

    detected_mime = _normalize_mime(magic.from_buffer(head, mime=True))
    allowed_mimes = ALLOWED_MIME_BY_EXTENSION[extension]
    if detected_mime not in allowed_mimes:
        raise UploadValidationError("Type MIME reel incoherent avec l'extension du fichier.")

    provided_mime = _normalize_mime(getattr(uploaded_file, "content_type", ""))
    if provided_mime and provided_mime not in allowed_mimes:
        raise UploadValidationError("Type MIME declare invalide pour ce format.")

    return {
        "filename": clean_name,
        "extension": extension,
        "detected_mime": detected_mime,
        "size": uploaded_file.size,
    }


def generate_safe_upload_filename(extension: str) -> str:
    """
    Generate a storage-safe randomized file name.

    Keeps only the validated extension, drops original user-provided file name.
    """
    normalized = (extension or "").lower().strip()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    if normalized not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("Extension de fichier invalide.")
    return f"{uuid.uuid4()}{normalized}"

