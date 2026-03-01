# apps/accounts/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.db.models import Sum
from django_ratelimit.decorators import ratelimit
from apps.enrollments.models import Inscription
from apps.absences.models import Absence
from apps.absences.utils import generate_absence_report
from apps.accounts.forms import CustomPasswordChangeForm, CustomAuthenticationForm
from apps.audits.ip_utils import ratelimit_client_ip, ratelimit_login_ip_username


@method_decorator(
    ratelimit(
        key=ratelimit_client_ip,
        rate=settings.LOGIN_RATE_LIMIT_IP,
        method='POST',
        block=False
    ),
    name='dispatch'
)
@method_decorator(
    ratelimit(
        key=ratelimit_login_ip_username,
        rate=settings.LOGIN_RATE_LIMIT_COMBINED,
        method='POST',
        block=False
    ),
    name='dispatch'
)
class RateLimitedLoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True
    authentication_form = CustomAuthenticationForm

    def dispatch(self, request, *args, **kwargs):
        if getattr(request, 'limited', False):
            messages.error(request, "Trop de tentatives de connexion. Reessayez dans quelques minutes.")
            response = self.render_to_response(self.get_context_data(form=self.get_form()), status=429)
            response['Retry-After'] = '300'
            return response
        return super().dispatch(request, *args, **kwargs)

@login_required
def profile_view(request):
    """
    Vue de profil qui utilise le bon template selon le rôle de l'utilisateur.
    """
    user = request.user
    context = {
        'user': user,
    }
    
    # Déterminer le template de base selon le rôle
    if user.role == user.Role.ADMIN:
        template = 'accounts/profile_admin.html'
    elif user.role == user.Role.SECRETAIRE:
        template = 'accounts/profile_secretary.html'
    elif user.role == user.Role.PROFESSEUR:
        template = 'accounts/profile_instructor.html'
    else:  # ETUDIANT
        template = 'accounts/profile_student.html'
    
    return render(request, template, context)

@login_required
def settings_view(request):
    """
    Page de paramètres pour l'étudiant.
    """
    user = request.user
    
    # Mock context for UI demonstration
    context = {
        'language': request.session.get('django_language', 'fr'), # Default to FR
        'two_factor_enabled': False, # Mock status
    }
    
    if request.method == 'POST':
        # Handle Language Switch (Session based)
        if 'language' in request.POST:
            request.session['django_language'] = request.POST.get('language')
            messages.success(request, "Préférence de langue mise à jour (Session).")
            
        # Handle 2FA Toggle (Mock)
        elif 'toggle_2fa' in request.POST:
            # In a real app, this would update a user field
            messages.info(request, "L'authentification à deux facteurs sera bientôt disponible.")
            
        return redirect('accounts:settings')

    return render(request, 'accounts/settings.html', context)

@login_required
def download_report_pdf(request):
    """
    Génère et télécharge le rapport PDF des absences.
    Réservé aux étudiants — chaque étudiant ne peut télécharger que son propre relevé.
    """
    from apps.accounts.models import User
    from apps.absences.services import get_system_threshold

    user = request.user
    if user.role != User.Role.ETUDIANT:
        messages.error(request, "Accès réservé aux étudiants.")
        return redirect('dashboard:index')

    system_threshold = get_system_threshold()
    inscriptions = Inscription.objects.filter(
        id_etudiant=user
    ).select_related('id_cours', 'id_annee')

    cours_data = []
    academic_year = "2024-2025"
    if inscriptions.exists():
        academic_year = inscriptions.first().id_annee.libelle

    for ins in inscriptions:
        total_abs = Absence.objects.filter(
            id_inscription=ins,
            statut__in=['NON_JUSTIFIEE', 'EN_ATTENTE'],
        ).aggregate(total=Sum('duree_absence'))['total'] or 0

        cours = ins.id_cours
        total_periodes = cours.nombre_total_periodes or 0
        seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        seuil_h = (total_periodes * seuil) / 100 if total_periodes > 0 else 0
        absence_rate = (total_abs / total_periodes) * 100 if total_periodes > 0 else 0
        is_eligible = total_abs < seuil_h

        cours_data.append({
            'nom': cours.nom_cours,
            'total_periods': total_periodes,
            'duree_absence': total_abs,
            'absence_rate': absence_rate,
            'status': is_eligible
        })
        
    response = HttpResponse(content_type='application/pdf')
    filename_safe = f"{user.prenom}_{user.nom}".replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="releve_absences_{filename_safe}.pdf"'
    
    generate_absence_report(response, user, academic_year, cours_data)
    
    return response


class CustomPasswordChangeView(auth_views.PasswordChangeView):
    """Vue personnalisée pour le changement de mot de passe qui désactive must_change_password"""
    template_name = 'accounts/password_change.html'
    form_class = CustomPasswordChangeForm
    
    def get_context_data(self, **kwargs):
        """Ajouter les paramètres système au contexte"""
        context = super().get_context_data(**kwargs)
        from apps.dashboard.models import SystemSettings
        settings = SystemSettings.get_settings()
        context['password_settings'] = {
            'min_length': settings.password_min_length,
            'require_uppercase': settings.password_require_uppercase,
            'require_lowercase': settings.password_require_lowercase,
            'require_numbers': settings.password_require_numbers,
            'require_special': settings.password_require_special,
        }
        return context
    
    def form_valid(self, form):
        """Désactiver le flag must_change_password après un changement réussi et rediriger vers le dashboard"""
        user = self.request.user
        must_change = hasattr(user, 'must_change_password') and user.must_change_password
        
        # Changer le mot de passe
        form.save()
        
        # Désactiver le flag must_change_password si nécessaire
        if must_change:
            user.must_change_password = False
            user.save(update_fields=['must_change_password'])
        
        messages.success(
            self.request,
            "Votre mot de passe a été modifié avec succès. Vous pouvez maintenant accéder à toutes les fonctionnalités."
        )
        
        # Rediriger vers le dashboard approprié selon le rôle
        from apps.accounts.models import User
        if user.role == User.Role.ETUDIANT:
            return redirect('dashboard:student_dashboard')
        elif user.role == User.Role.PROFESSEUR:
            return redirect('dashboard:instructor_dashboard')
        elif user.role == User.Role.ADMIN:
            return redirect('dashboard:admin_dashboard')
        elif user.role == User.Role.SECRETAIRE:
            return redirect('dashboard:secretary_dashboard')
        else:
            return redirect('dashboard:index')
