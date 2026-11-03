from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, UsernameField
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class FirstRunSetupForm(UserCreationForm):
    """One-time first-run setup (Sprint 24, ADR-049): the installer
    admin's credentials plus the first company's name.

    Password confirmation and the full AUTH_PASSWORD_VALIDATORS set
    are inherited from UserCreationForm — its ``_post_clean`` runs
    ``validate_password`` and attaches failures to the form, so a
    weak password creates nothing. The company side reuses the
    organizations app's own CompanyForm at save time (see views):
    the setup form asks only for the company name and the remaining
    CompanyForm fields take their model defaults there, exactly as
    the companies UI's own form presents them.
    """

    company_name = forms.CharField(label=_("نام شرکت"), max_length=200)

    class Meta:
        # Mirrors UserCreationForm.Meta (model + username field class);
        # restated because django-stubs does not expose the base Meta.
        model = User
        fields = ("username",)
        field_classes = {"username": UsernameField}


class ProfileForm(forms.ModelForm):
    """Self-service profile (Sprint 27, ADR-052): the signed-in user
    edits their OWN display fields — first name, last name, email.

    The username is deliberately NOT a field: it is the login
    identity, the axes lockout key, and the name audit trails refer
    to, so it is shown read-only in the template and can never be
    changed through this form (a POST smuggling a ``username`` value
    is simply ignored — the form has no such field). Email is safe
    to edit: authentication and axes key on the username alone, and
    nothing else treats email as identity (it is not unique on the
    model and no flow reads it).
    """

    first_name = forms.CharField(label=_("نام"), max_length=150, required=False)
    last_name = forms.CharField(label=_("نام خانوادگی"), max_length=150, required=False)
    email = forms.EmailField(label=_("ایمیل"), required=False)

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")
