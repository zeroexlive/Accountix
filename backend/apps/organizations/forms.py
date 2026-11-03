from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, UsernameField
from django.utils.translation import gettext_lazy as _

from apps.organizations.models import Company, CompanyMembership, FiscalPeriod, FiscalYear

User = get_user_model()


class FiscalCloseForm(forms.Form):
    """Retained-earnings picker for period/year closing (Sprint 13).

    ADR-028/011: the closing entry moves the period result into a
    retained-earnings account the *user* picks per closing — nothing
    is hardcoded. Eligibility is the Sprint 12 GL-picker rule (active,
    postable, same company), narrowed to EQUITY accounts.
    """

    retained_earnings: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=None, label=_("حساب سود (زیان) انباشته"), required=True
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounting.forms import eligible_accounts

        if company is not None:
            self.fields["retained_earnings"].queryset = eligible_accounts(company, "EQUITY")


class AttachMemberForm(forms.Form):
    """Add an EXISTING system user to a company by exact username
    (Sprint 26, ADR-051). The product is offline-first, so there are
    no email invites: the owner types the username of an account
    that already exists on this install. Unknown usernames and
    already-members are friendly field errors; the service repeats
    the membership check so the model's unique constraint can never
    leak as an IntegrityError. The resolved user lands on
    ``form.user`` after validation."""

    username = forms.CharField(label=_("نام کاربری"), max_length=150)
    role = forms.ChoiceField(label=_("نقش"), choices=CompanyMembership.Role.choices)

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.user = None

    def clean_username(self):
        username = self.cleaned_data["username"]
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise forms.ValidationError(_("کاربری با این نام کاربری یافت نشد.")) from None
        if (
            self.company is not None
            and CompanyMembership.objects.filter(company=self.company, user=user).exists()
        ):
            raise forms.ValidationError(_("این کاربر از قبل عضو این شرکت است."))
        self.user = user
        return username


class CreateMemberUserForm(UserCreationForm):
    """Create a NEW user inline and attach them to the company
    (Sprint 26, ADR-051). Password confirmation and the full
    AUTH_PASSWORD_VALIDATORS set are inherited from UserCreationForm
    — the Sprint 24 setup form's approach (ADR-049): a weak password
    or a duplicate username is a form error and nothing is created.
    The membership itself is written by the service, in the same
    transaction as the user."""

    first_name = forms.CharField(label=_("نام"), max_length=150, required=False)
    last_name = forms.CharField(label=_("نام خانوادگی"), max_length=150, required=False)
    role = forms.ChoiceField(label=_("نقش"), choices=CompanyMembership.Role.choices)

    class Meta:
        # Mirrors UserCreationForm.Meta (model + username field class);
        # restated because django-stubs does not expose the base Meta.
        model = User
        fields = ("username", "first_name", "last_name")
        field_classes = {"username": UsernameField}


class MemberRoleForm(forms.Form):
    """The per-row role picker on the members page (Sprint 26)."""

    role = forms.ChoiceField(choices=CompanyMembership.Role.choices)


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["name", "legal_name", "registration_number", "default_currency"]
        # Explicit labels (Sprint 30, ADR-055): no verbose_names on
        # the models, so auto-generated English labels would render
        # verbatim in the Persian UI.
        labels = {
            "name": _("نام"),
            "legal_name": _("نام قانونی"),
            "registration_number": _("شماره ثبت"),
            "default_currency": _("ارز پیش‌فرض"),
        }


class FiscalYearForm(forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = ["company", "name", "start_date", "end_date", "status"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "company": _("شرکت"),
            "name": _("نام"),
            "start_date": _("تاریخ شروع"),
            "end_date": _("تاریخ پایان"),
            "status": _("وضعیت"),
        }


class FiscalPeriodForm(forms.ModelForm):
    class Meta:
        model = FiscalPeriod
        fields = ["company", "fiscal_year", "name", "start_date", "end_date", "status"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "company": _("شرکت"),
            "fiscal_year": _("سال مالی"),
            "name": _("نام"),
            "start_date": _("تاریخ شروع"),
            "end_date": _("تاریخ پایان"),
            "status": _("وضعیت"),
        }
