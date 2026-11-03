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
