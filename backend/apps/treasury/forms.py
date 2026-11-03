"""Treasury data-entry forms (Sprint 12, ADR-039).

Forms collect input only: treasury accounts, payments, allocations
and cheque transitions all go through ``treasury.services`` — the
only writer of invoice ``payment_status`` remains the service's
recompute (ADR-024), and allocations are voided, never deleted
(ADR-025). GL accounts are picked per payment from the company's
eligible accounts (ADR-011); a cheque's holding account is chosen at
payment posting time, as the cheque model requires (ADR-026).
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounting.forms import account_field
from apps.accounting.models import Account
from apps.core.forms import date_widget
from apps.organizations.models import Company
from apps.parties.models import Party
from apps.treasury.models import BankStatementLine, ChequeLeaf, Payment, TreasuryAccount


class TreasuryAccountForm(forms.Form):
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label=_("شرکت")
    )
    kind = forms.ChoiceField(choices=TreasuryAccount.Kind.choices, label=_("نوع حساب"))
    name = forms.CharField(max_length=200, label=_("نام حساب"))
    bank_name = forms.CharField(max_length=200, required=False, label=_("نام بانک"))
    account_number = forms.CharField(max_length=64, required=False, label=_("شماره حساب"))
    gl_account = forms.ModelChoiceField(queryset=Account.objects.none(), label=_("حساب دفتر کل"))

    def __init__(self, *args, company=None, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        self.fields["gl_account"] = account_field(company, "ASSET", label=_("حساب دفتر کل"))


class PaymentForm(forms.Form):
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label=_("شرکت")
    )
    direction = forms.ChoiceField(choices=Payment.Direction.choices, label=_("جهت"))
    party = forms.ModelChoiceField(queryset=Party.objects.none(), label=_("طرف‌حساب"))
    treasury_account = forms.ModelChoiceField(
        queryset=TreasuryAccount.objects.none(), label=_("حساب خزانه")
    )
    method = forms.ChoiceField(choices=Payment.Method.choices, label=_("روش"))
    amount = forms.DecimalField(max_digits=19, decimal_places=2, label=_("مبلغ"))
    payment_date = forms.DateField(widget=date_widget(), label=_("تاریخ"))
    reference = forms.CharField(max_length=64, required=False, label=_("شماره ارجاع"))
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("توضیحات")
    )
    # Cheque details — required only when method is CHEQUE (see clean()).
    cheque_bank_name = forms.CharField(max_length=200, required=False, label=_("بانک صادرکننده چک"))
    cheque_number = forms.CharField(max_length=64, required=False, label=_("شماره چک"))
    sayad_id = forms.CharField(max_length=64, required=False, label=_("شناسه صیاد"))
    cheque_issue_date = forms.DateField(
        widget=date_widget(), required=False, label=_("تاریخ صدور چک")
    )
    cheque_due_date = forms.DateField(widget=date_widget(), required=False, label=_("سررسید چک"))
    # Cheque book leaf (Sprint 15, ADR-042) — only added in __init__
    # when the company actually has UNUSED leaves; see below.

    def __init__(self, *args, company=None, companies=None, direction=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            parties = Party.objects.filter(company=company, is_active=True)
            if direction == Payment.Direction.RECEIPT:
                parties = parties.filter(kind__in=[Party.Kind.CUSTOMER, Party.Kind.BOTH])
            elif direction == Payment.Direction.PAYMENT:
                parties = parties.filter(kind__in=[Party.Kind.SUPPLIER, Party.Kind.BOTH])
            self.fields["party"].queryset = parties.order_by("code")
            self.fields["treasury_account"].queryset = TreasuryAccount.objects.filter(
                company=company, is_active=True
            ).order_by("name")
            self._add_leaf_field(company)

    def _add_leaf_field(self, company):
        """Offer the UNUSED cheque-book leaves of the company, grouped
        by book, as an optional picker. When the company has no unused
        leaves the field is absent entirely and free cheque-number
        entry works exactly as before cheque books existed."""
        leaves = (
            ChequeLeaf.objects.filter(company=company, status=ChequeLeaf.Status.UNUSED)
            .select_related("book", "treasury_account")
            .order_by("treasury_account__name", "book__created_at", "position")
        )
        groups = {}
        for leaf in leaves:
            book = leaf.book
            group_label = _("دفترچه %(book)s — حساب %(account)s") % {
                "book": book.label or book.first_number,
                "account": leaf.treasury_account.name,
            }
            groups.setdefault(group_label, []).append((str(leaf.pk), leaf.number))
        if not groups:
            return
        choices = [("", _("— بدون برگ؛ شماره آزاد —"))]
        choices.extend((label, options) for label, options in groups.items())
        self.fields["leaf"] = forms.ChoiceField(
            choices=choices,
            required=False,
            label=_("برگ دفترچه چک (فقط چک پرداختی)"),
            help_text=_(
                "با انتخاب برگ، شماره چک از روی برگ خوانده می‌شود و برگ مصرف‌شده علامت می‌خورد."
            ),
        )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("method") == Payment.Method.CHEQUE:
            if not cleaned.get("cheque_number") and not cleaned.get("leaf"):
                self.add_error("cheque_number", _("برای روش چک، شماره چک لازم است."))
            if not cleaned.get("cheque_due_date"):
                self.add_error("cheque_due_date", _("برای روش چک، سررسید چک لازم است."))
        return cleaned


class PaymentPostForm(forms.Form):
    """Counterparty (+ cheque holding) account pickers for posting a
    payment. Fields are built from the payment itself: receipts need a
    receivable account, payments a payable account, and cheque
    payments additionally the holding account of ADR-026."""

    def __init__(self, *args, payment, **kwargs):
        super().__init__(*args, **kwargs)
        company = payment.company
        if payment.direction == Payment.Direction.RECEIPT:
            self.fields["receivable"] = account_field(company, "ASSET", label=_("حساب دریافتنی"))
            if payment.method == Payment.Method.CHEQUE:
                self.fields["cheques_in_hand"] = account_field(
                    company, "ASSET", label=_("حساب چک‌های دریافتی نزد صندوق")
                )
        else:
            self.fields["payable"] = account_field(company, "LIABILITY", label=_("حساب پرداختنی"))
            if payment.method == Payment.Method.CHEQUE:
                self.fields["cheques_payable"] = account_field(
                    company, "LIABILITY", label=_("حساب چک‌های پرداختی")
                )


class AllocationForm(forms.Form):
    """One amount input per open invoice of the payment's party.

    Fields are added dynamically (``amount_<n>`` alongside the item
    list the view passes in); blank or zero rows are ignored, and each
    positive row is allocated by the service on its own — the service
    caps the amounts against both the payment and the invoice.
    """

    def __init__(self, *args, items=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.items = list(items)
        for idx, item in enumerate(self.items):
            invoice = item["invoice"]
            self.fields[f"amount_{idx}"] = forms.DecimalField(
                max_digits=19,
                decimal_places=2,
                required=False,
                min_value=0,
                label=_("%(invoice_number)s — مانده %(outstanding)s")
                % {"invoice_number": invoice.invoice_number, "outstanding": item["outstanding"]},
            )


class ChequeClearForm(forms.Form):
    """Clearing a RECEIVED cheque needs the bank treasury account the
    money lands in (issued cheques clear against the payment's own
    treasury account, so they need no picker)."""

    bank_treasury_account = forms.ModelChoiceField(
        queryset=TreasuryAccount.objects.none(), label=_("حساب بانکی مقصد")
    )
    clearing_date = forms.DateField(widget=date_widget(), required=False, label=_("تاریخ وصول"))

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["bank_treasury_account"].queryset = TreasuryAccount.objects.filter(
                company=company, is_active=True, kind=TreasuryAccount.Kind.BANK
            ).order_by("name")


class BankStatementForm(forms.Form):
    """New bank statement header (Sprint 14, ADR-041). Opening and
    closing balances are the bank's stated figures; the account
    picker offers only BANK treasury accounts of the scoped company."""

    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label=_("شرکت")
    )
    treasury_account = forms.ModelChoiceField(
        queryset=TreasuryAccount.objects.none(), label=_("حساب بانکی")
    )
    start_date = forms.DateField(
        widget=date_widget(),
        label=_("از تاریخ (میلادی)"),
        help_text=_("تاریخ‌ها به میلادی وارد می‌شوند؛ نمایش در سامانه جلالی است."),
    )
    end_date = forms.DateField(widget=date_widget(), label=_("تا تاریخ (میلادی)"))
    opening_balance = forms.DecimalField(
        max_digits=19, decimal_places=2, label=_("مانده ابتدای دوره (طبق بانک)")
    )
    closing_balance = forms.DecimalField(
        max_digits=19, decimal_places=2, label=_("مانده پایان دوره (طبق بانک)")
    )
    source_note = forms.CharField(max_length=500, required=False, label=_("منبع / توضیح"))

    def __init__(self, *args, company=None, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            self.fields["treasury_account"].queryset = TreasuryAccount.objects.filter(
                company=company, is_active=True, kind=TreasuryAccount.Kind.BANK
            ).order_by("name")


class BankStatementLineForm(forms.Form):
    """One manually added statement line. The amount is signed from
    the bank's perspective: positive = money in (bank credit),
    negative = money out (bank debit)."""

    line_date = forms.DateField(widget=date_widget(), label=_("تاریخ (میلادی)"))
    description = forms.CharField(max_length=500, required=False, label=_("شرح"))
    reference = forms.CharField(max_length=64, required=False, label=_("شماره ارجاع"))
    amount = forms.DecimalField(
        max_digits=19,
        decimal_places=2,
        label=_("مبلغ (با علامت)"),
        help_text=_("واریز به حساب مثبت و برداشت از حساب منفی وارد شود."),
    )


class StatementImportForm(forms.Form):
    """Statement-file upload for statement lines (Sprint 18,
    ADR-044): CSV, CAMT.053 and OFX are detected by file content in
    ``treasury.statement_files``; the row contract lives in
    ``treasury.reconciliation``."""

    file = forms.FileField(
        label=_("فایل صورت‌حساب"),
        help_text=_(
            "قالب‌های پشتیبانی‌شده: CSV (ستون‌های date, description, reference, amount یا debit و credit)، CAMT.053 و OFX/QFX. قالب از روی محتوای فایل تشخیص داده می‌شود و هر فایل فقط یک صورت‌حساب است. تاریخ‌ها میلادی و مبلغ با علامت بانک است."
        ),
        widget=forms.FileInput(attrs={"accept": ".csv,.ofx,.qfx,.xml"}),
    )


class StatementFilePreviewForm(forms.Form):
    """Upload a statement file on the create page (Sprint 18): the
    file is parsed and its header (period, opening/closing balances)
    prefills the create form as editable values; confirming the
    create form then builds the statement and imports the rows."""

    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label=_("شرکت")
    )
    treasury_account = forms.ModelChoiceField(
        queryset=TreasuryAccount.objects.none(), label=_("حساب بانکی")
    )
    statement_file = forms.FileField(
        label=_("فایل صورت‌حساب"),
        help_text=_(
            "CSV یا CAMT.053 یا OFX/QFX؛ قالب از روی محتوا تشخیص داده می‌شود و هر فایل یک صورت‌حساب است."
        ),
        widget=forms.FileInput(attrs={"accept": ".csv,.ofx,.qfx,.xml"}),
    )

    def __init__(self, *args, company=None, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            self.fields["treasury_account"].queryset = TreasuryAccount.objects.filter(
                company=company, is_active=True, kind=TreasuryAccount.Kind.BANK
            ).order_by("name")


class ChequeBookForm(forms.Form):
    """New cheque book (Sprint 15, ADR-042): one BANK treasury
    account, the printed number of the first leaf, and how many
    leaves the book holds. The service generates the whole range and
    rejects any overlap with the account's existing leaves."""

    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label=_("شرکت")
    )
    treasury_account = forms.ModelChoiceField(
        queryset=TreasuryAccount.objects.none(), label=_("حساب بانکی")
    )
    label = forms.CharField(max_length=200, required=False, label=_("عنوان دفترچه"))
    first_number = forms.CharField(
        max_length=64,
        label=_("شماره اولین برگ"),
        help_text=_(
            "بخش عددی انتهای شماره، شمارنده برگ‌هاست؛ مثلاً شروع از 1001 یعنی برگ‌ها 1001، 1002، …"
        ),
    )
    leaf_count = forms.IntegerField(
        min_value=1, max_value=1000, label=_("تعداد برگ"), help_text=_("بین ۱ تا ۱۰۰۰ برگ.")
    )

    def __init__(self, *args, company=None, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            self.fields["treasury_account"].queryset = TreasuryAccount.objects.filter(
                company=company, is_active=True, kind=TreasuryAccount.Kind.BANK
            ).order_by("name")


class StatementMatchForm(forms.Form):
    """Manual match: one book movement (hidden id, rendered per row)
    plus the statement line chosen for it."""

    journal_line = forms.UUIDField(widget=forms.HiddenInput)
    statement_line = forms.ModelChoiceField(
        queryset=BankStatementLine.objects.none(), label=_("ردیف صورت‌حساب")
    )

    def __init__(self, *args, statement=None, **kwargs):
        super().__init__(*args, **kwargs)
        if statement is not None:
            self.fields["statement_line"].queryset = statement.lines.filter(
                matched_journal_line__isnull=True
            )
