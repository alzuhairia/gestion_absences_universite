"""
FICHIER : apps/utils.py
RESPONSABILITE : Utilitaires partagés entre toutes les apps Django.

  safe_get_page       — pagination sécurisée (fallback page 1)
  generate_qr_data_uri — QR code PNG encodé base64 (utilisé par absences/QR et MFA)
  pdf_check_page_break — nouvelle page ReportLab si y < marge (PDF exports)
  excel_safe_cell     — neutralise les formules dans les cellules Excel (injection CSV)
"""
import base64
import io

import qrcode
from django.core.paginator import EmptyPage, PageNotAnInteger


def safe_get_page(paginator, page_number):
    """Return the requested page, falling back to page 1 for any invalid input."""
    try:
        return paginator.page(page_number or 1)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)


def generate_qr_data_uri(url: str) -> str:
    """Encode a URL as a PNG QR code and return a base64 data-URI. No disk I/O."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def pdf_check_page_break(p, page_height, y, margin=80):
    """Create a new ReportLab page if y is near the bottom; return the new y."""
    if y < margin:
        p.showPage()
        return page_height - 50
    return y


def excel_safe_cell(val) -> str:
    """Prefix cells starting with formula chars to prevent CSV/Excel injection."""
    s = str(val) if val is not None else ""
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s
