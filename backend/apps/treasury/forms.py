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

from apps.accounting.forms import account_field
from apps.accounting.models import Account
from apps.core.forms import date_widget
from apps.organizations.models import Company
from apps.parties.models import Party
from apps.treasury.models import BankStatementLine, Payment, TreasuryAccount


class TreasuryAccountForm(forms.Form):
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label="شرکت"
    )
    kind = forms.ChoiceField(choices=TreasuryAccount.Kind.choices, label="نوع حساب")
    name = forms.CharField(max_length=200, label="نام حساب")
    bank_name = forms.CharField(max_length=200, required=False, label="نام بانک")
    account_number = forms.CharField(max_length=64, required=False, label="شماره حساب")
    gl_account = forms.ModelChoiceField(queryset=Account.objects.none(), label="حساب دفتر کل")

    def __init__(self, *args, company=None, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        self.fields["gl_account"] = account_field(company, "ASSET", label="حساب دفتر کل")


class PaymentForm(forms.Form):
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label="شرکت"
    )
    direction = forms.ChoiceField(choices=Payment.Direction.choices, label="جهت")
    party = forms.ModelChoiceField(queryset=Party.objects.none(), label="طرف‌حساب")
    treasury_account = forms.ModelChoiceField(
        queryset=TreasuryAccount.objects.none(), label="حساب خزانه"
    )
    method = forms.ChoiceField(choices=Payment.Method.choices, label="روش")
    amount = forms.DecimalField(max_digits=19, decimal_places=2, label="مبلغ")
    payment_date = forms.DateField(widget=date_widget(), label="تاریخ")
    reference = forms.CharField(max_length=64, required=False, label="شماره ارجاع")
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="توضیحات"
    )
    # Cheque details — required only when method is CHEQUE (see clean()).
    cheque_bank_name = forms.CharField(max_length=200, required=False, label="بانک صادرکننده چک")
    cheque_number = forms.CharField(max_length=64, required=False, label="شماره چک")
    sayad_id = forms.CharField(max_length=64, required=False, label="شناسه صیاد")
    cheque_issue_date = forms.DateField(widget=date_widget(), required=False, label="تاریخ صدور چک")
    cheque_due_date = forms.DateField(widget=date_widget(), required=False, label="سررسید چک")

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

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("method") == Payment.Method.CHEQUE:
            if not cleaned.get("cheque_number"):
                self.add_error("cheque_number", "برای روش چک، شماره چک لازم است.")
            if not cleaned.get("cheque_due_date"):
                self.add_error("cheque_due_date", "برای روش چک، سررسید چک لازم است.")
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
            self.fields["receivable"] = account_field(company, "ASSET", label="حساب دریافتنی")
            if payment.method == Payment.Method.CHEQUE:
                self.fields["cheques_in_hand"] = account_field(
                    company, "ASSET", label="حساب چک‌های دریافتی نزد صندوق"
                )
        else:
            self.fields["payable"] = account_field(company, "LIABILITY", label="حساب پرداختنی")
            if payment.method == Payment.Method.CHEQUE:
                self.fields["cheques_payable"] = account_field(
                    company, "LIABILITY", label="حساب چک‌های پرداختی"
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
                label=f"{invoice.invoice_number} — مانده {item['outstanding']}",
            )


class ChequeClearForm(forms.Form):
    """Clearing a RECEIVED cheque needs the bank treasury account the
    money lands in (issued cheques clear against the payment's own
    treasury account, so they need no picker)."""

    bank_treasury_account = forms.ModelChoiceField(
        queryset=TreasuryAccount.objects.none(), label="حساب بانکی مقصد"
    )
    clearing_date = forms.DateField(widget=date_widget(), required=False, label="تاریخ وصول")

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
        queryset=Company.objects.none(), widget=forms.HiddenInput, label="شرکت"
    )
    treasury_account = forms.ModelChoiceField(
        queryset=TreasuryAccount.objects.none(), label="حساب بانکی"
    )
    start_date = forms.DateField(
        widget=date_widget(),
        label="از تاریخ (میلادی)",
        help_text="تاریخ‌ها به میلادی وارد می‌شوند؛ نمایش در سامانه جلالی است.",
    )
    end_date = forms.DateField(widget=date_widget(), label="تا تاریخ (میلادی)")
    opening_balance = forms.DecimalField(
        max_digits=19, decimal_places=2, label="مانده ابتدای دوره (طبق بانک)"
    )
    closing_balance = forms.DecimalField(
        max_digits=19, decimal_places=2, label="مانده پایان دوره (طبق بانک)"
    )
    source_note = forms.CharField(max_length=500, required=False, label="منبع / توضیح")

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

    line_date = forms.DateField(widget=date_widget(), label="تاریخ (میلادی)")
    description = forms.CharField(max_length=500, required=False, label="شرح")
    reference = forms.CharField(max_length=64, required=False, label="شماره ارجاع")
    amount = forms.DecimalField(
        max_digits=19,
        decimal_places=2,
        label="مبلغ (با علامت)",
        help_text="واریز به حساب مثبت و برداشت از حساب منفی وارد شود.",
    )


class StatementImportForm(forms.Form):
    """CSV upload for statement lines — the column contract lives in
    ``treasury.reconciliation.import_statement_lines``."""

    file = forms.FileField(
        label="فایل CSV صورت‌حساب",
        help_text="ستون‌ها: date, description, reference, amount (یا debit و credit). تاریخ‌ها میلادی (YYYY-MM-DD) و مبلغ با علامت بانک است.",
    )


class StatementMatchForm(forms.Form):
    """Manual match: one book movement (hidden id, rendered per row)
    plus the statement line chosen for it."""

    journal_line = forms.UUIDField(widget=forms.HiddenInput)
    statement_line = forms.ModelChoiceField(
        queryset=BankStatementLine.objects.none(), label="ردیف صورت‌حساب"
    )

    def __init__(self, *args, statement=None, **kwargs):
        super().__init__(*args, **kwargs)
        if statement is not None:
            self.fields["statement_line"].queryset = statement.lines.filter(
                matched_journal_line__isnull=True
            )
