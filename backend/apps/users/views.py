"""Authentication views: the login view plus the first-run setup
(Sprint 24, ADR-049).

The setup trigger lives ONLY on the login view — no middleware — so
every other anonymous surface (health, static, set_language) keeps
exactly its previous behaviour. The funnel: the launcher opens the
browser at /login/, and the dashboard's login_required redirect also
lands on /login/ (LOGIN_URL), so with an empty user table every
real first-run journey reaches the login view and is handed to
/setup/ from there.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _

from apps.organizations.forms import CompanyForm
from apps.organizations.models import Company, CompanyMembership
from apps.users.forms import FirstRunSetupForm, ProfileForm

User = get_user_model()

# login() is told the backend explicitly: AUTHENTICATION_BACKENDS
# starts with axes' standalone backend, whose authenticate() needs
# the HTTP request; the user here was just created by the form, not
# authenticated, and ModelBackend is the credential backend of record.
LOGIN_BACKEND = "django.contrib.auth.backends.ModelBackend"


def first_run_setup_available() -> bool:
    """True only in the one-time bootstrap window: the kill switch is
    on (settings.FIRST_RUN_SETUP_ENABLED, env ACCOUNTIX_FIRST_RUN_SETUP)
    and no user row exists yet."""
    return bool(settings.FIRST_RUN_SETUP_ENABLED) and not User.objects.exists()


class SetupAwareLoginView(LoginView):
    """Stock login, except that a zero-user install is redirected to
    the first-run setup instead — for GET (render) and POST alike:
    with no users there is nothing to log in with."""

    template_name = "registration/login.html"

    def dispatch(self, request, *args, **kwargs):
        if first_run_setup_available():
            return redirect("setup")
        return super().dispatch(request, *args, **kwargs)


def first_run_setup(request):
    """GET renders the setup form; a valid POST creates, in ONE
    transaction, the installer admin (staff + superuser — the person
    installing is the owner; product-level authority is the OWNER
    membership), the first company through the organizations UI's own
    CompanyForm, and the OWNER membership — then logs the admin in
    and lands on the dashboard. Once any user exists the page is
    dead: every request redirects away and nothing is processed."""
    if not first_run_setup_available():
        if request.user.is_authenticated:
            return redirect("dashboard")
        return redirect("login")
    form = FirstRunSetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # The company goes through the organizations UI's own
        # CompanyForm. The setup form asks only for the name; every
        # other CompanyForm field takes its model default — the same
        # values the company form itself renders as initials (e.g.
        # default_currency="IRR") — so the created company is exactly
        # what the UI's create view would produce from a name.
        company_data = {
            field.name: field.get_default()
            for field in Company._meta.fields
            if field.name in CompanyForm().fields and field.has_default()
        }
        company_data["name"] = form.cleaned_data["company_name"]
        company_form = CompanyForm(data=company_data)
        if company_form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.is_staff = True
                user.is_superuser = True
                user.save()
                company = company_form.save()
                CompanyMembership.objects.create(
                    company=company, user=user, role=CompanyMembership.Role.OWNER
                )
            login(request, user, backend=LOGIN_BACKEND)
            messages.success(request, _("راه‌اندازی اولیه کامل شد؛ خوش آمدید."))
            return redirect("dashboard")
        # Defensive only: company_name's constraints mirror the
        # CompanyForm name field, so this cannot disagree in
        # practice; surface any error on the company field anyway.
        for field_name, errors in company_form.errors.items():
            for error in errors:
                form.add_error("company_name" if field_name == "name" else None, error)
    return render(request, "registration/setup.html", {"form": form})


# ---------------------------------------------------------------------------
# Sprint 27 — self-service account surface (ADR-052)
#
# These routes are deliberately NOT company-scoped and carry NO user
# id: the subject is always ``request.user`` themself, so one user
# can never reach another's page — there is nothing to scope or to
# leak. Available to every signed-in user regardless of role.
# ---------------------------------------------------------------------------


@login_required
def profile(request):
    """Edit your own first/last name and email. The username is
    displayed read-only in the template and is not a form field
    (ADR-052), so it cannot change here."""
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("پروفایل شما به‌روزرسانی شد."))
        return redirect("profile")
    return render(request, "users/profile.html", {"form": form})


class AccountPasswordChangeView(LoginRequiredMixin, SuccessMessageMixin, PasswordChangeView):
    """Change your own password with Django's built-in machinery:
    PasswordChangeForm requires the current password and runs the
    new one through the full AUTH_PASSWORD_VALIDATORS set, and the
    view calls update_session_auth_hash on success so THIS session
    stays signed in while every other session's hash goes stale
    (ADR-052). Failed attempts here never touch django-axes: the
    form verifies the current password via user.check_password()
    directly — no authenticate() call, no user_login_failed signal,
    so nothing is recorded toward the login lockout."""

    template_name = "users/password_change.html"
    success_url = reverse_lazy("profile")
    success_message = _("گذرواژه شما تغییر کرد.")
