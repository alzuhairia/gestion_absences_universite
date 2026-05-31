"""
Utilitaires partagés entre toutes les applications Django.

Responsabilités :
  - safe_get_page : pagination sécurisée avec repli sur la page 1
  - generate_qr_data_uri : code QR PNG encodé en data URI base64 (utilisé par absences/QR et MFA)
  - pdf_check_page_break : nouvelle page ReportLab si y < marge (exports PDF)
  - excel_safe_cell : neutralise les formules dans les cellules Excel (prévention d'injection CSV)

Fait partie des utilitaires partagés de UniAbsences.
"""
import base64
import io

import qrcode
from django.core.paginator import EmptyPage, PageNotAnInteger


def safe_get_page(paginator, page_number):
    """
    Retourne la page demandée, en se repliant sur la page 1 pour toute entrée invalide.

    Paramètres :
        paginator : instance de Paginator de Django.
        page_number : numéro de page demandé (peut être None ou invalide).

    Retourne :
        Page : la page demandée ou la page 1 si invalide.
    """
    try:
        return paginator.page(page_number or 1)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)


def generate_qr_data_uri(url: str) -> str:
    """
    Encode une URL sous forme de code QR PNG et retourne un data URI base64. Aucune E/S disque.

    Paramètres :
        url (str) : l'URL à encoder dans le code QR.

    Retourne :
        str : un data URI contenant le code QR PNG encodé en base64.
    """
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def pdf_check_page_break(p, page_height, y, margin=80):
    """
    Crée une nouvelle page ReportLab si y est proche du bas ; retourne le nouveau y.

    Paramètres :
        p : canvas ReportLab.
        page_height (float) : hauteur totale de la page.
        y (float) : position y actuelle.
        margin (float) : seuil de marge inférieure.

    Retourne :
        float : nouvelle position y (après saut de page si nécessaire).
    """
    if y < margin:
        p.showPage()
        return page_height - 50
    return y


def excel_safe_cell(val) -> str:
    """
    Préfixe les cellules commençant par des caractères de formule pour prévenir l'injection CSV/Excel.

    Paramètres :
        val : la valeur à assainir.

    Retourne :
        str : chaîne assainie, sûre pour l'export Excel/CSV.
    """
    s = str(val) if val is not None else ""
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s
