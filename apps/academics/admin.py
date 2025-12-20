from django.contrib import admin
from .models import Faculte, Departement, Cours

@admin.register(Faculte)
class FaculteAdmin(admin.ModelAdmin):
    list_display = ('id_faculte', 'nom_faculte')

@admin.register(Departement)
class DepartementAdmin(admin.ModelAdmin):
    list_display = ('id_departement', 'nom_departement', 'id_faculte')

@admin.register(Cours)
class CoursAdmin(admin.ModelAdmin):
    list_display = ('code_cours', 'nom_cours', 'id_departement')