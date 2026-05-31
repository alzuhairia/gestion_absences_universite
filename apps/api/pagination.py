"""
Configuration de pagination pour l'API REST UniAbsences.

Ce module fournit une classe de pagination unique et réutilisable, référencée
par chaque ViewSet de la couche API. L'utilisation d'une classe partagée
maintient un comportement de taille de page cohérent sur tous les endpoints et
rend tout ajustement futur trivial.

Responsabilités :
  - Définir la taille de page par défaut pour les réponses de liste paginées.
  - Permettre aux consommateurs de l'API de remplacer la taille de page via un
    paramètre de requête, jusqu'à un maximum configuré.

Fait partie de l'API REST UniAbsences.
"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """
    Pagination par numéro de page utilisée par tous les ViewSets UniAbsences.

    Comportement :
      - Taille de page par défaut  : 20 enregistrements par page.
      - Surcharge client           : passer ``?page_size=N`` pour demander une taille différente.
      - Taille de page maximale    : 100 enregistrements — les requêtes de page plus grande
                                     sont silencieusement plafonnées à cette valeur par DRF.

    Utilisation :
        Définir ``pagination_class = StandardPagination`` sur tout ViewSet pour activer
        les réponses paginées automatiques pour les actions ``list``.
    """

    # Nombre d'enregistrements renvoyés lorsque le client ne spécifie pas page_size
    page_size = 20

    # Nom du paramètre de requête que les clients utilisent pour demander une taille de page personnalisée
    page_size_query_param = "page_size"

    # Plafond strict — empêche les réponses excessivement volumineuses
    max_page_size = 100
