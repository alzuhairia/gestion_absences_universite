from django.contrib import admin
from .models import Absence, Justification

@admin.register(Absence)
class AbsenceAdmin(admin.ModelAdmin):
    list_display = ('id_absence', 'id_inscription', 'type_absence', 'statut')
    list_filter = ('statut', 'type_absence')

@admin.register(Justification)
class JustificationAdmin(admin.ModelAdmin):
    list_display = ('id_justification', 'id_absence', 'validee')
