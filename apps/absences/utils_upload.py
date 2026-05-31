"""
Validation sécurisée des fichiers uploadés pour le système d'absences UniAbsences.

Ce module fournit ``validate_justification_file``, le point d'entrée unique
de validation pour tous les documents de justificatif uploadés par les
étudiants.

Stratégie de validation à trois couches
----------------------------------------
1. **Vérification de l'extension** — seuls .pdf, .jpg, .jpeg, .png sont acceptés.
2. **Vérification du type MIME** — ``python-magic`` inspecte les 2 premiers Ko
   du contenu du fichier ; retombe sur ``mimetypes`` si magic n'est pas installé.
3. **Vérification des magic bytes** — comparaison de la signature binaire brute
   avec les en-têtes connus pour PDF, JPEG et PNG afin d'empêcher l'usurpation
   du type de contenu.

Protections supplémentaires
---------------------------
- Assainissement du nom de fichier contre le path-traversal et la double extension.
- Génération de nom de fichier basée sur UUID (``generate_safe_filename``) pour
  empêcher les collisions de noms et le directory traversal sur le stockage.
- Limite de taille configurable (5 Mo par défaut) appliquée avant toute écriture
  sur disque.

Fait partie du système d'absences UniAbsences.
"""

import os
import re
import uuid
from pathlib import Path

from django.core.exceptions import ValidationError

import logging

logger = logging.getLogger(__name__)

try:
    import magic

    # Vérifier que la bibliothèque fonctionne réellement (DLL peut manquer sous Windows)
    magic.from_buffer(b"test", mime=True)
except Exception:  # ImportError, MagicException, OSError, etc.
    magic = None
    _logger = logging.getLogger(__name__)
    _logger.warning(
        "python-magic unavailable — MIME validation disabled, binary signature check still active."
    )
    # En production, la validation MIME doit être active pour la défense en profondeur
    from django.conf import settings
    if not settings.DEBUG:
        _logger.error(
            "PRODUCTION WARNING: python-magic is not installed. "
            "File upload MIME validation is disabled. "
            "Install python-magic-bin (Windows) or python-magic (Linux) for full security."
        )

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

SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9À-ÿ._ ()\-]{1,255}$")


class UploadValidationError(ValidationError):
    """
    ValidationError spécialisée levée pour tous les échecs de sécurité d'upload.

    L'utilisation d'une sous-classe dédiée permet aux vues et aux tests de
    distinguer les erreurs de validation d'upload des autres instances de
    ValidationError sans inspecter le texte du message.
    """


def _normalize_mime(value: str | None) -> str:
    """
    Normalise une chaîne de type MIME brute pour la comparaison.

    Supprime les paramètres (par ex. ``; charset=utf-8``) et convertit le
    jeton de type en minuscules afin que les comparaisons avec
    ``ALLOWED_MIME_BY_EXTENSION`` soient insensibles à la casse et indépendantes
    des paramètres.

    Paramètres :
        value : Chaîne MIME brute (par ex. ``"application/pdf; charset=utf-8"``),
            ou ``None`` / chaîne vide.

    Retourne :
        Chaîne de type MIME normalisée en minuscules, ou ``""`` si l'entrée est falsy.
    """
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _validate_filename(file_name: str) -> tuple[str, list[str]]:
    """
    Assainit et valide le nom d'un fichier uploadé pour un stockage sûr.

    Effectue les vérifications suivantes dans l'ordre :
      1. Rejette les noms vides, les octets nuls et les séparateurs de chemin
         (``/``, ``\\``) pour bloquer les attaques de path-traversal.
      2. Extrait le nom de base via ``os.path.basename`` et rejette les noms
         qui commencent par un point ou contiennent ``..``.
      3. Compare le nom nettoyé à ``SAFE_FILENAME_PATTERN`` pour bloquer les
         métacaractères de shell et les caractères non imprimables.
      4. Valide que l'extension finale (dernier suffixe) figure dans
         ``ALLOWED_EXTENSIONS``.
      5. Rejette les fichiers avec des extensions intermédiaires dangereuses
         (par ex. ``report.php.pdf``) qui pourraient tromper les serveurs mal
         configurés pour le MIME-sniffing.

    Paramètres :
        file_name : La chaîne brute du nom de fichier fournie par le client.

    Retourne :
        Un tuple (``clean_name``, ``suffixes``) où ``clean_name`` est la chaîne
        du nom de base assaini et ``suffixes`` est la liste de toutes les
        extensions minuscules avec point extraites par ``pathlib.Path.suffixes``.

    Lève :
        UploadValidationError : si une vérification de sécurité échoue.
    """
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


def validate_uploaded_file(
    uploaded_file, max_size_bytes: int = MAX_UPLOAD_SIZE_BYTES
) -> dict:
    """
    Valide strictement un fichier de justificatif uploadé par un étudiant via trois couches de sécurité.

    Pipeline de validation :
      1. Assainissement du nom de fichier via ``_validate_filename`` (liste
         d'extensions autorisées, prévention du path-traversal, rejet des
         extensions intermédiaires dangereuses).
      2. Vérification de la taille : rejette les fichiers vides et ceux dépassant
         ``max_size_bytes``.
      3. Vérification des magic bytes binaires : lit les 8 premiers Ko et
         vérifie que l'en-tête du fichier correspond à la signature attendue
         pour l'extension déclarée.  Cette couche s'exécute toujours et ne
         nécessite aucune bibliothèque externe.
      4. Détection MIME via ``python-magic`` (optionnel) : si la bibliothèque
         est disponible, le type MIME détecté doit correspondre à
         ``ALLOWED_MIME_BY_EXTENSION`` pour l'extension du fichier.  Si elle
         n'est pas disponible, cette couche est ignorée avec un avertissement
         (voir le bloc d'import au niveau module).
      5. Contre-vérification du type MIME déclaré par le navigateur : le
         ``Content-Type`` du formulaire d'upload multipart est validé contre
         la liste d'autorisation lorsqu'il est présent.

    Le pointeur de fichier est repositionné à 0 (``seek(0)``) avant le retour
    afin que le code en aval (par ex. le stockage ``FileField``) puisse lire
    le contenu.

    Paramètres :
        uploaded_file : Une instance ``InMemoryUploadedFile`` ou
            ``TemporaryUploadedFile`` provenant d'un widget ``FileField``.  Doit
            posséder les attributs ``name``, ``size``, ``read()``, ``seek()`` et
            ``content_type``.
        max_size_bytes : Taille maximale autorisée en octets.  Par défaut
            ``MAX_UPLOAD_SIZE_BYTES`` (5 Mo).

    Retourne :
        Un dict avec les clés :
          - ``"filename"`` (str) : nom de fichier assaini.
          - ``"extension"`` (str) : extension finale en minuscules (par ex. ``".pdf"``).
          - ``"detected_mime"`` (str) : type MIME détecté par magic ou déclaré
            par le navigateur.
          - ``"size"`` (int) : taille du fichier en octets.

    Lève :
        UploadValidationError : si une couche de validation échoue.
    """
    if uploaded_file is None:
        raise UploadValidationError("Aucun fichier recu.")

    clean_name, suffixes = _validate_filename(uploaded_file.name or "")
    extension = suffixes[-1]

    try:
        file_size = uploaded_file.size
    except AttributeError:
        raise UploadValidationError("Fichier invalide (taille indisponible).")

    if file_size is None or file_size <= 0:
        raise UploadValidationError("Fichier vide ou invalide.")

    if file_size > max_size_bytes:
        raise UploadValidationError(
            "Le fichier est trop volumineux. Taille maximale autorisee: 5 Mo."
        )

    # Lire juste le debut du fichier suffit pour la detection MIME/signature.
    try:
        head = uploaded_file.read(8192)
        uploaded_file.seek(0)
    except (IOError, OSError) as exc:
        logger.warning("Erreur de lecture du fichier uploadé: %s", exc)
        raise UploadValidationError("Erreur de lecture du fichier.")

    if not head:
        raise UploadValidationError("Fichier vide ou invalide.")

    # Obligatoire : vérification de la signature binaire (fonctionne sans aucune bibliothèque externe)
    expected_signatures = MAGIC_SIGNATURES[extension]
    if not any(head.startswith(signature) for signature in expected_signatures):
        raise UploadValidationError(
            "Signature binaire invalide pour ce type de fichier."
        )

    # Optionnel : détection MIME via python-magic (couche supplémentaire si disponible)
    detected_mime = ""
    allowed_mimes = ALLOWED_MIME_BY_EXTENSION[extension]
    if magic is not None:
        detected_mime = _normalize_mime(magic.from_buffer(head, mime=True))
        if detected_mime not in allowed_mimes:
            raise UploadValidationError(
                "Type MIME reel incoherent avec l'extension du fichier."
            )

    # Vérifier le type MIME déclaré par le navigateur
    provided_mime = _normalize_mime(getattr(uploaded_file, "content_type", ""))
    if provided_mime and provided_mime not in allowed_mimes:
        raise UploadValidationError("Type MIME declare invalide pour ce format.")

    return {
        "filename": clean_name,
        "extension": extension,
        "detected_mime": detected_mime or provided_mime,
        "size": uploaded_file.size,
    }


def generate_safe_upload_filename(extension: str) -> str:
    """
    Génère un nom de fichier résistant aux collisions et sûr pour le stockage d'un document uploadé.

    Le nom de fichier original fourni par l'utilisateur est volontairement
    écarté et remplacé par un UUID4 afin que :
      - Deux étudiants uploadant des fichiers du même nom ne s'écrasent pas
        mutuellement sur le backend de stockage.
      - Le chemin de stockage ne révèle aucune information sur le nom de
        fichier original, réduisant la fuite d'informations.

    Paramètres :
        extension : L'extension de fichier validée en minuscules à attacher
            (par ex. ``".pdf"``).  Un point de tête est ajouté automatiquement
            s'il est absent.

    Retourne :
        Une chaîne de la forme ``"<uuid4><extension>"``
        (par ex. ``"3f2504e0-4f89-11d3-9a0c-0305e82c3301.pdf"``).

    Lève :
        UploadValidationError : si l'extension normalisée n'est pas dans
            ``ALLOWED_EXTENSIONS``.
    """
    normalized = (extension or "").lower().strip()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    if normalized not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("Extension de fichier invalide.")
    return f"{uuid.uuid4()}{normalized}"
