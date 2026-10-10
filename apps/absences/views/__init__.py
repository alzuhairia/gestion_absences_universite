"""
Initialisation du package de vues des absences — apps/absences/views/__init__.py

Ce package regroupe toutes les vues HTTP du système de gestion d'absences
UniAbsences. Chaque sous-module couvre un rôle ou un domaine fonctionnel
distinct, afin de garder des fichiers courts et ciblés.

Convention de nommage
---------------------
Le préfixe du fichier reflète le rôle appelant, pas uniquement le sujet
métier : par exemple ``secretary_student_history_api`` consulte l'historique
d'un *étudiant* mais vit dans ``secretary_absence_encoding.py`` parce que
seul le secrétariat l'invoque.

Organisation des sous-modules
-----------------------------
student_views.py
    Vues côté étudiant : détails d'absence, upload de justificatif et
    téléchargement de document.

professor_views.py  (hub de ré-export)
    Agrège les vues de présence du professeur depuis deux sous-modules :
      - professor_session.py      : ``session_create`` (point d'entrée unifié
                                    de création de séance — mode manuel ou QR)
                                    et ``validate_session`` (verrouillage définitif).
      - professor_attendance.py   : hub de ré-export des deux vues de marquage :
          - professor_attendance_form.py  : ``mark_absence`` (formulaire pleine page).
          - professor_attendance_htmx.py  : ``mark_absence_htmx`` (fragment HTMX).

qr_views.py  (hub de ré-export)
    Agrège toutes les vues QR de présence depuis trois sous-modules :
      - qr_utils.py       : helpers GPS (Haversine), génération d'image QR,
                            hachage SHA-256 du jeton, et journalisation des tentatives.
      - qr_professor.py   : ``qr_generate``, ``qr_dashboard``,
                            ``qr_refresh_token``, ``qr_finalize``.
      - qr_student.py     : ``qr_scan`` (endpoint étudiant anti-fraude GPS).

secretary_views.py  (hub de ré-export)
    Agrège toutes les vues secrétariat depuis trois sous-modules :
      - secretary_justification.py     : ``review_justification``,
                                         ``validation_list``,
                                         ``process_justification``,
                                         ``justified_absences_list``.
      - secretary_absence_encoding.py  : ``create_justified_absence``,
                                         ``secretary_student_history_api``.
      - secretary_absence_edit.py      : ``edit_absence`` (édition directe
                                         d'un enregistrement d'absence).

Tous les symboles publics sont ré-exportés ici afin qu'``absences/urls.py``
puisse importer depuis le chemin unique et stable
``apps.absences.views.*``, sans dépendre de la structure interne des
sous-modules.

Fait partie du système d'absences UniAbsences.
"""

from .student_views import (
    absence_details,
    upload_justification,
    download_justification,
)
from .professor_views import (
    session_create,
    mark_absence,
    mark_absence_htmx,
    validate_session,
)
from .qr_views import (
    qr_generate,
    qr_dashboard,
    qr_refresh_token,
    qr_finalize,
    qr_scan,
)
from .secretary_views import (
    review_justification,
    validation_list,
    process_justification,
    create_justified_absence,
    justified_absences_list,
    secretary_student_history_api,
    edit_absence,
)

__all__ = [
    "absence_details",
    "upload_justification",
    "download_justification",
    "session_create",
    "mark_absence",
    "mark_absence_htmx",
    "validate_session",
    "review_justification",
    "qr_generate",
    "qr_dashboard",
    "qr_refresh_token",
    "qr_finalize",
    "qr_scan",
    "validation_list",
    "process_justification",
    "create_justified_absence",
    "justified_absences_list",
    "secretary_student_history_api",
    "edit_absence",
]
