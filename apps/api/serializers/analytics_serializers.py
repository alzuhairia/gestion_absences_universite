"""
FICHIER : apps/api/serializers/analytics_serializers.py
RESPONSABILITE : Serializers DRF pour les donnees analytiques du tableau de bord.
"""
from rest_framework import serializers


class DashboardAnalyticsSerializer(serializers.Serializer):
    academic_year = serializers.CharField(allow_null=True)
    total_students = serializers.IntegerField()
    total_professors = serializers.IntegerField()
    total_secretaries = serializers.IntegerField()
    active_courses = serializers.IntegerField()
    total_inscriptions = serializers.IntegerField()
    total_absences = serializers.IntegerField()
    students_at_risk = serializers.IntegerField()
    critical_actions_7d = serializers.IntegerField()


class StatisticsAnalyticsSerializer(serializers.Serializer):
    academic_year = serializers.CharField(allow_null=True)
    top_professors = serializers.ListField()
    top_courses = serializers.ListField()
    monthly_absences = serializers.ListField()
    absences_by_department = serializers.ListField()
    absences_by_status = serializers.ListField()
    absences_by_level = serializers.ListField()
