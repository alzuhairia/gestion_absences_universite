"""
Scan QR côté étudiant — apps/absences/views/qr_student.py

``qr_scan``
    Gère l'intégralité du flux de présence par QR pour l'étudiant en deux phases :

    GET  — Page de confirmation. L'étudiant voit les informations du cours / de
           la séance et, si la vérification GPS est requise, le navigateur
           demande la position de l'appareil avant que le formulaire puisse
           être soumis.

    POST — Enregistrement de la présence. La vue exécute tous les contrôles de
           sécurité, enregistre la présence dans ``QRScanRecord`` et journalise
           la tentative dans ``QRScanLog`` quel que soit le résultat.

Contrôles de sécurité (dans l'ordre)
------------------------------------
1. Le token est actif (``QRAttendanceToken.is_active``).
2. Le token n'a pas expiré (``QRAttendanceToken.is_expired``).
3. La séance n'est pas verrouillée (``Seance.validated``).
4. L'étudiant est inscrit au cours pour l'année académique en cours.
5. Aucun scan en doublon pour cette séance (contrainte d'unicité sur
   ``QRScanRecord``, appliquée à la fois côté application et côté base via
   ``select_for_update()``).
6. Contrôle de distance GPS (quand ``verify_location=True`` sur le token) :
   - Les coordonnées de l'étudiant doivent être valides (non ``None`` et
     non proches du point Null Island).
   - La distance doit se situer dans le rayon autorisé en utilisant soit le
     GPS de l'établissement depuis ``SystemSettings``, soit les coordonnées
     du token du professeur comme point de référence.

Mesures anti-fraude
-------------------
- Chaque tentative de scan — réussie ou non — est inscrite dans ``QRScanLog``
  avec un hash SHA-256 du token (le token brut n'est jamais stocké en journal).
- Les coordonnées Null Island (lat/lng ≈ 0.0) sont explicitement rejetées
  pour empêcher l'usurpation triviale du GPS.
- ``QRScanRecord`` possède une contrainte d'unicité au niveau base de données
  sur ``(seance, inscription)`` ; une ``IntegrityError`` lors de soumissions
  concurrentes en doublon est interceptée et renvoyée comme résultat
  « duplicate ».

Fait partie du système de présence UniAbsences.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from ..models import QRAttendanceToken, QRScanLog, QRScanRecord
from .qr_utils import (
    _get_establishment_gps,
    _haversine,
    _is_valid_coordinate,
    _log_scan_attempt,
)
from apps.audits.utils import get_client_ip
from apps.dashboard.decorators import student_required
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@student_required
@require_http_methods(["GET", "POST"])
def qr_scan(request, token):
    """
    Gère le scan du QR code par l'étudiant : afficher la confirmation (GET) ou enregistrer la présence (POST).

    GET
        Rend ``absences/qr_scan.html`` avec les informations du cours / de la
        séance et le drapeau ``gps_required`` afin que le template puisse
        demander la position de l'appareil avant la soumission du formulaire.

    POST
        Exécute tous les contrôles de sécurité et GPS, enregistre la présence
        dans ``QRScanRecord``, journalise la tentative dans ``QRScanLog`` et
        rend ``absences/qr_scan_result.html`` avec un statut parmi
        ``"success"``, ``"duplicate"``, ``"expired"`` ou ``"error"``.

    Flux de vérification GPS (lorsque ``qr_token.verify_location`` vaut ``True``)
    --------------------------------------------------------------------------
    Priorité 1 : utiliser le GPS de l'établissement depuis ``SystemSettings``
                 comme point de référence quand lat/lng sont tous deux
                 configurés.
    Priorité 2 : se rabattre sur les coordonnées du token du professeur.
    Repli : retourner une erreur de configuration — l'application du GPS sans
            point de référence n'est pas possible.

    Scans suspects
    --------------
    Lorsque le GPS n'est pas requis mais que les coordonnées de l'étudiant
    sont tout de même soumises, la distance par rapport au point de référence
    du token est calculée. Si elle dépasse
    ``QRAttendanceToken.DISTANCE_THRESHOLD_METERS``, l'enregistrement est
    marqué comme suspect (``QRScanRecord.is_suspicious = True``) et
    l'étudiant est averti.

    Paramètres
    ----------
    request : HttpRequest
        La requête HTTP entrante.
    token : UUID
        La valeur ``QRAttendanceToken.token`` issue de l'URL (intégrée
        dans le QR).

    Retour
    ------
    HttpResponse
        ``qr_scan.html`` rendu (GET) ou ``qr_scan_result.html`` rendu (POST).

    Lève
    ----
    Http404
        Quand aucun token n'existe avec l'UUID fourni.
    """
    qr_token = get_object_or_404(QRAttendanceToken, token=token)
    seance = qr_token.seance
    course = seance.id_cours
    # Dictionnaire de contexte partagé pour tous les rendus d'erreur en sortie anticipée.
    error_ctx = {"course": course, "seance": seance}

    # Contrôle 1 : le token doit être actif (non désactivé manuellement par le professeur).
    if not qr_token.is_active:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_INACTIVE)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Ce QR code n'est plus actif.",
        })

    # Contrôle 2 : le token ne doit pas être expiré (expiration temporelle).
    if qr_token.is_expired:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_EXPIRED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "expired",
            "message": "Ce QR code a expiré. Scannez le nouveau QR affiché par le professeur.",
        })

    # Contrôle 3 : la séance ne doit pas être verrouillée (finalisée ou validée manuellement).
    if seance.validated:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_LOCKED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Cette séance est déjà validée et verrouillée.",
        })

    # Contrôle 4 : l'étudiant doit être activement inscrit à ce cours pour l'année.
    inscription = Inscription.objects.filter(
        id_etudiant=request.user,
        id_cours=course,
        id_annee=seance.id_annee,
        status=Inscription.Status.EN_COURS,
    ).first()

    if not inscription:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_NOT_ENROLLED)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "error",
            "message": "Vous n'êtes pas inscrit à ce cours.",
        })

    # Contrôle 5 (pré-verrou) : vérification rapide de doublon avant d'entrer dans la transaction.
    # La vérification définitive a lieu à l'intérieur de la transaction pour gérer les conditions de course.
    existing = QRScanRecord.objects.filter(seance=seance, inscription=inscription).first()
    if existing:
        _log_scan_attempt(request, seance, qr_token,
                          QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_DUPLICATE)
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "duplicate",
            "message": "Votre présence a déjà été enregistrée.",
            "scanned_at": existing.scanned_at,
        })

    gps_required = qr_token.verify_location
    etab_lat, etab_lng, etab_radius = _get_establishment_gps()

    # GET : rend la page de confirmation ; aucune présence n'est encore enregistrée.
    if request.method == "GET":
        return render(request, "absences/qr_scan.html", {
            "qr_token": qr_token,
            "course": course,
            "seance": seance,
            "gps_required": gps_required,
        })

    # --- POST : enregistrement de la présence ---

    # Récupère les coordonnées GPS soumises par le navigateur de l'étudiant.
    stu_lat_raw = request.POST.get("latitude", "").strip()
    stu_lng_raw = request.POST.get("longitude", "").strip()
    gps_status_val = request.POST.get("gps_status", "")

    stu_lat_f = stu_lng_f = distance = None
    try:
        if stu_lat_raw and stu_lng_raw:
            stu_lat_f = float(stu_lat_raw)
            stu_lng_f = float(stu_lng_raw)
    except (ValueError, TypeError):
        stu_lat_f = stu_lng_f = None

    # Bloc d'application du GPS — exécuté uniquement lorsque verify_location est activé.
    if gps_required:
        if gps_status_val == "refused":
            # L'étudiant a explicitement refusé l'accès à la position — impossible de continuer.
            _log_scan_attempt(request, seance, qr_token,
                              QRScanLog.GPSStatus.REFUSED, QRScanLog.ScanResult.REJECTED_GPS)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "La localisation est obligatoire pour cette séance.",
            })

        # Contrôle Null Island — des coordonnées proches de (0,0) sont probablement falsifiées.
        if not _is_valid_coordinate(stu_lat_f) or not _is_valid_coordinate(stu_lng_f):
            _log_scan_attempt(request, seance, qr_token,
                              QRScanLog.GPSStatus.UNAVAILABLE, QRScanLog.ScanResult.REJECTED_GPS)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "Impossible de récupérer votre position. Réessayez ou contactez le professeur.",
            })

        # Contrôle de distance — privilégier le GPS de l'établissement à celui du professeur sur le token.
        if _is_valid_coordinate(etab_lat) and _is_valid_coordinate(etab_lng):
            # Utilise la référence GPS de l'établissement configurée dans SystemSettings.
            distance = _haversine(etab_lat, etab_lng, stu_lat_f, stu_lng_f)
            if distance > etab_radius:
                assert distance is not None
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.ACCEPTED, QRScanLog.ScanResult.REJECTED_DISTANCE,
                                  stu_lat_f, stu_lng_f, distance)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "error",
                    "message": f"Vous n'êtes pas dans la zone autorisée. Distance : {distance:.0f} m (max : {etab_radius} m).",
                    "distance": round(distance, 0),
                    "radius": etab_radius,
                })
        elif qr_token.latitude is not None and qr_token.longitude is not None:
            # Repli sur la position du professeur stockée sur le token.
            distance = _haversine(qr_token.latitude, qr_token.longitude, stu_lat_f, stu_lng_f)
            if distance > QRAttendanceToken.DISTANCE_THRESHOLD_METERS:
                assert distance is not None
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.ACCEPTED, QRScanLog.ScanResult.REJECTED_DISTANCE,
                                  stu_lat_f, stu_lng_f, distance)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "error",
                    "message": f"Vous n'êtes pas dans la zone autorisée. Distance : {distance:.0f} m.",
                    "distance": round(distance, 0),
                    "radius": QRAttendanceToken.DISTANCE_THRESHOLD_METERS,
                })
        else:
            # Le GPS est requis mais ni l'établissement ni le token n'ont de
            # coordonnées de référence valides — c'est une erreur de configuration.
            logger.warning("Vérification GPS activée mais aucune coordonnée de référence (séance %s)", seance.id_seance)
            return render(request, "absences/qr_scan_result.html", {
                **error_ctx, "scan_status": "error",
                "message": "Erreur de configuration GPS. Contactez le secrétariat ou le professeur.",
            })

    # Construit les kwargs pour le QRScanRecord.
    scan_kwargs = {
        "seance": seance,
        "student": request.user,
        "inscription": inscription,
        "ip_address": get_client_ip(request),
    }

    is_suspicious = False
    if stu_lat_f is not None and stu_lng_f is not None:
        scan_kwargs["latitude"] = stu_lat_f
        scan_kwargs["longitude"] = stu_lng_f

        # Calcule la distance depuis l'origine du token même lorsque le GPS n'est pas requis,
        # afin que le professeur puisse repérer les scans anormalement éloignés sur le tableau de bord.
        if distance is None and qr_token.latitude is not None:
            distance = _haversine(qr_token.latitude, qr_token.longitude, stu_lat_f, stu_lng_f)
        if distance is not None:
            assert distance is not None
            scan_kwargs["distance_meters"] = round(distance, 1)
            # Signale comme suspect si l'étudiant dépasse le seuil même lorsque
            # l'application du GPS n'est pas activée (non bloquant, informatif).
            is_suspicious = distance > QRAttendanceToken.DISTANCE_THRESHOLD_METERS
            scan_kwargs["is_suspicious"] = is_suspicious

    # Vérification définitive de doublon à l'intérieur de la transaction — gère la condition
    # de course où deux requêtes arrivent en même temps pour le même étudiant.
    try:
        with transaction.atomic():
            dup = (
                QRScanRecord.objects
                .select_for_update()
                .filter(seance=seance, inscription=inscription)
                .first()
            )
            if dup:
                _log_scan_attempt(request, seance, qr_token,
                                  QRScanLog.GPSStatus.NOT_REQUIRED, QRScanLog.ScanResult.REJECTED_DUPLICATE)
                return render(request, "absences/qr_scan_result.html", {
                    **error_ctx, "scan_status": "duplicate",
                    "message": "Votre présence a déjà été enregistrée.",
                    "scanned_at": dup.scanned_at,
                })
            # Tous les contrôles sont passés — enregistre la présence.
            QRScanRecord.objects.create(**scan_kwargs)
    except IntegrityError:
        # La contrainte d'unicité au niveau base a intercepté un insert concurrent — traité comme doublon.
        return render(request, "absences/qr_scan_result.html", {
            **error_ctx, "scan_status": "duplicate",
            "message": "Votre présence a déjà été enregistrée.",
        })

    # Journalise le scan réussi (le statut GPS reflète si des coordonnées ont été fournies).
    gps_log_status = (
        QRScanLog.GPSStatus.ACCEPTED if stu_lat_f is not None
        else QRScanLog.GPSStatus.NOT_REQUIRED
    )
    _log_scan_attempt(request, seance, qr_token, gps_log_status,
                      QRScanLog.ScanResult.VALIDATED, stu_lat_f, stu_lng_f, distance)

    # Construit le contexte de succès — avertit l'étudiant si sa position a été signalée.
    result_ctx = {**error_ctx, "scan_status": "success"}
    if is_suspicious:
        assert distance is not None
        result_ctx["message"] = "Présence enregistrée, mais votre position est éloignée de la salle de cours."
        result_ctx["distance"] = round(distance, 0)
    else:
        result_ctx["message"] = "Présence enregistrée avec succès !"

    return render(request, "absences/qr_scan_result.html", result_ctx)
