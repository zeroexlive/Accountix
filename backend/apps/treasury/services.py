"""Treasury application services (Sprint 06).

All money movement goes through here. Rules enforced, in the house
style of the previous sprints (validate everything before writing,
``transaction.atomic`` everywhere, Decimal money, no hardcoded GL
account codes):

- A payment posts its journal through ``accounting.services`` with
  idempotency key ``payment:<id>``. The debit/credit side that is money
  itself comes from the treasury account's own GL link; the AR/AP side
  is supplied by the caller per payment and stored on the payment.
- A received CHEQUE does not touch cash/bank: it debits a
  caller-supplied cheques-in-hand account (ADR-026). Clearing moves the
  value into a bank treasury account; bouncing/returning reverses the
  receipt effect back onto the party's receivable.
- An issued CHEQUE credits a caller-supplied cheques-payable account
  at posting; clearing debits that account and credits the bank the
  cheque is drawn on (the payment's own treasury account).
- Allocations exist only on POSTED payments (ADR-023). The allocation
  service is the ONLY writer of invoice ``payment_status`` (ADR-024),
  recomputed from ACTIVE allocations after every change.
- Allocation rows are voided, never deleted (ADR-025).
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

ZERO = Decimal("0")

# Legal cheque transitions (ADR-026). Terminal: CLEARED, BOUNCED,
# RETURNED, REVERSED.
_CHEQUE_TRANSITIONS = {
    "RECEIVED": {"DEPOSITED", "CLEARED", "BOUNCED", "RETURNED", "REVERSED"},
    "DEPOSITED": {"CLEARED", "BOUNCED", "RETURNED", "REVERSED"},
    "DELIVERED": {"CLEARED", "BOUNCED", "REVERSED"},
    "CLEARED": set(),
    "BOUNCED": set(),
    "RETURNED": set(),
    "REVERSED": set(),
}


def _assert_cheque_transition(cheque, target):
    allowed = _CHEQUE_TRANSITIONS.get(cheque.status, set())
    if target not in allowed:
        raise ValidationError(
            _("Cheque cannot move from %(status)s to %(target)s.")
            % {"status": cheque.status, "target": target}
        )


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------


def create_treasury_account(*, company, kind, name, gl_account, bank_name="", account_number=""):
    from apps.treasury.models import TreasuryAccount

    if gl_account is None or gl_account.company_id != company.id:
        raise ValidationError(_("GL account belongs to a different company (or is missing)."))
    if not gl_account.is_active or not gl_account.is_postable:
        raise ValidationError(_("GL account must be active and postable."))
    if kind == TreasuryAccount.Kind.BANK and not bank_name.strip():
        raise ValidationError(_("A bank treasury account needs a bank name."))
    return TreasuryAccount.objects.create(
        company=company,
        kind=kind,
        name=name,
        gl_account=gl_account,
        bank_name=bank_name,
        account_number=account_number,
    )


def _validate_treasury_account(company, treasury_account):
    if treasury_account is None or treasury_account.company_id != company.id:
        raise ValidationError(_("Treasury account belongs to a different company (or is missing)."))
    if not treasury_account.is_active:
        raise ValidationError(_("Treasury account is inactive."))
    gl = treasury_account.gl_account
    if gl.company_id != company.id or not gl.is_active or not gl.is_postable:
        raise ValidationError(_("Treasury account's GL account is not postable for this company."))


def _validate_gl_account(company, account, label):
    if account is None:
        raise ValidationError(
            _("A %(label)s GL account is required for this payment.") % {"label": label}
        )
    if account.company_id != company.id:
        raise ValidationError(
            _("The %(label)s account belongs to a different company.") % {"label": label}
        )
    if not account.is_active or not account.is_postable:
        raise ValidationError(
            _("The %(label)s account must be active and postable.") % {"label": label}
        )
    return account


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@transaction.atomic
def create_payment(
    *,
    company,
    direction,
    party,
    treasury_account,
    amount,
    payment_date,
    method="CASH",
    reference="",
    description="",
    cheque=None,
    leaf=None,
):
    """Create a DRAFT payment. ``cheque`` (a dict) attaches a DRAFT-stage
    Cheque row when method is CHEQUE: keys bank_name, cheque_number,
    due_date, and optionally sayad_id, issue_date, amount (defaults to
    the payment amount and must equal it).

    ``leaf`` (a ChequeLeaf, Sprint 15 / ADR-042) is the opt-in cheque
    book control for ISSUED cheques: when given, the leaf must be an
    UNUSED leaf of the payment's own treasury account, the cheque
    takes its number from the leaf (a conflicting entered number is
    rejected), and the leaf flips to USED, linked to the new cheque —
    all inside this transaction. When omitted, behaviour is exactly
    what it was before cheque books existed."""
    from apps.treasury.models import Cheque, ChequeLeaf, Payment

    amount = Decimal(str(amount))
    if amount <= ZERO:
        raise ValidationError(_("Payment amount must be positive."))
    _validate_treasury_account(company, treasury_account)
    if leaf is not None and method != Payment.Method.CHEQUE:
        raise ValidationError(_("A cheque book leaf can only be used for a CHEQUE payment."))
    payment = Payment.objects.create(
        company=company,
        direction=direction,
        party=party,
        treasury_account=treasury_account,
        method=method,
        amount=amount,
        payment_date=payment_date,
        reference=reference,
        description=description,
    )
    if method == Payment.Method.CHEQUE:
        if not cheque:
            raise ValidationError(_("A CHEQUE payment needs cheque details."))
        cheque_amount = Decimal(str(cheque.get("amount", amount)))
        if cheque_amount != amount:
            raise ValidationError(_("Cheque amount must equal the payment amount."))
        direction_c = (
            Cheque.Direction.RECEIVED
            if direction == Payment.Direction.RECEIPT
            else Cheque.Direction.ISSUED
        )
        initial = (
            Cheque.Status.RECEIVED
            if direction_c == Cheque.Direction.RECEIVED
            else Cheque.Status.DELIVERED
        )
        locked_leaf = None
        cheque_number = cheque.get("cheque_number", "")
        if leaf is not None:
            if direction != Payment.Direction.PAYMENT:
                raise ValidationError(
                    _(
                        "Cheque book leaves are only for issued (outgoing) cheques; "
                        "received cheques are the other party's paper."
                    )
                )
            from apps.treasury import cheque_books as cheque_book_services

            locked_leaf = cheque_book_services.consume_leaf(
                leaf, company=company, treasury_account=treasury_account
            )
            entered = (cheque_number or "").strip()
            if entered and entered != locked_leaf.number:
                raise ValidationError(
                    _(
                        "The entered cheque number %(entered)s does not match the "
                        "selected leaf %(leaf)s."
                    )
                    % {"entered": entered, "leaf": locked_leaf.number}
                )
            cheque_number = locked_leaf.number
        cheque_row = Cheque.objects.create(
            company=company,
            direction=direction_c,
            payment=payment,
            bank_name=cheque.get("bank_name", ""),
            cheque_number=cheque_number,
            sayad_id=cheque.get("sayad_id", ""),
            amount=cheque_amount,
            issue_date=cheque.get("issue_date"),
            due_date=cheque["due_date"],
            status=initial,
        )
        if locked_leaf is not None:
            locked_leaf.status = ChequeLeaf.Status.USED
            locked_leaf.cheque = cheque_row
            locked_leaf.save(update_fields=["status", "cheque", "updated_at"])
    elif cheque:
        raise ValidationError(_("Cheque details are only accepted for CHEQUE payments."))
    return payment


@transaction.atomic
def post_payment(payment, *, user=None, gl_accounts=None):
    """Post a DRAFT payment: journal + cheque holding account.

    ``gl_accounts`` keys: ``receivable`` (receipts) or ``payable``
    (payments); plus ``cheques_in_hand`` for received cheques and
    ``cheques_payable`` for issued cheques. Re-posting a POSTED payment
    returns it unchanged (idempotent)."""
    from apps.accounting.services import post_journal_entry
    from apps.audit.services import record_event
    from apps.parties.services import require_customer, require_supplier
    from apps.treasury.models import Payment

    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.POSTED:
        return payment
    if payment.status != Payment.Status.DRAFT:
        raise ValidationError(_("Only a DRAFT payment can be posted."))

    gl_accounts = gl_accounts or {}
    company = payment.company
    if payment.direction == Payment.Direction.RECEIPT:
        require_customer(company, payment.party)
        counterparty = _validate_gl_account(company, gl_accounts.get("receivable"), "receivable")
    else:
        require_supplier(company, payment.party)
        counterparty = _validate_gl_account(company, gl_accounts.get("payable"), "payable")
    _validate_treasury_account(company, payment.treasury_account)

    cheque = payment.cheques.first() if payment.method == Payment.Method.CHEQUE else None
    if payment.method == Payment.Method.CHEQUE and cheque is None:
        raise ValidationError(_("CHEQUE payment has no cheque attached."))

    money_account = payment.treasury_account.gl_account
    if cheque is not None:
        if cheque.direction == "RECEIVED":
            money_account = _validate_gl_account(
                company, gl_accounts.get("cheques_in_hand"), "cheques-in-hand"
            )
        else:
            money_account = _validate_gl_account(
                company, gl_accounts.get("cheques_payable"), "cheques-payable"
            )

    if payment.direction == Payment.Direction.RECEIPT:
        lines = [
            {"account": money_account, "debit": payment.amount},
            {"account": counterparty, "credit": payment.amount, "party": payment.party},
        ]
    else:
        lines = [
            {"account": counterparty, "debit": payment.amount, "party": payment.party},
            {"account": money_account, "credit": payment.amount},
        ]
    entry = post_journal_entry(
        company=company,
        entry_date=payment.payment_date,
        lines=lines,
        description=payment.description or f"{payment.direction} {payment.reference}".strip(),
        user=user,
        source_type="PAYMENT",
        source_id=str(payment.id),
        idempotency_key=f"payment:{payment.id}",
    )
    payment.journal_entry = entry
    payment.counterparty_account = counterparty
    payment.status = Payment.Status.POSTED
    payment.posted_by = user
    payment.posted_at = timezone.now()
    payment.save()
    if cheque is not None:
        cheque.holding_account = money_account
        cheque.save(update_fields=["holding_account", "updated_at"])
    record_event(
        action="payment.posted",
        entity_type="Payment",
        company=company,
        user=user,
        entity_id=payment.id,
        direction=payment.direction,
        amount=str(payment.amount),
    )
    return payment


# ---------------------------------------------------------------------------
# Allocations + payment_status (ADR-023/024/025)
# ---------------------------------------------------------------------------


def allocated_total_for_payment(payment):
    from apps.treasury.models import PaymentAllocation

    agg = PaymentAllocation.objects.filter(
        payment=payment, status=PaymentAllocation.Status.ACTIVE
    ).aggregate(total=Sum("amount"))
    return agg["total"] or ZERO


def allocated_total_for_invoice(invoice):
    from apps.purchases.models import PurchaseInvoice
    from apps.treasury.models import PaymentAllocation

    field = "sales_invoice" if not isinstance(invoice, PurchaseInvoice) else "purchase_invoice"
    agg = PaymentAllocation.objects.filter(
        status=PaymentAllocation.Status.ACTIVE, **{field: invoice}
    ).aggregate(total=Sum("amount"))
    return agg["total"] or ZERO


def recompute_payment_status(invoice):
    """The ONLY writer of invoice payment_status (ADR-024): derive it
    from ACTIVE allocations vs the invoice grand total and save."""

    allocated = allocated_total_for_invoice(invoice)
    if allocated <= ZERO:
        new_status = invoice.PaymentStatus.UNPAID
    elif allocated < invoice.grand_total:
        new_status = invoice.PaymentStatus.PARTIALLY_PAID
    else:
        new_status = invoice.PaymentStatus.PAID
    if invoice.payment_status != new_status:
        invoice.payment_status = new_status
        invoice.save(update_fields=["payment_status", "updated_at"])
    return invoice


@transaction.atomic
def allocate_payment(payment, invoice, amount, *, user=None):
    """Allocate part of a POSTED payment to a POSTED invoice and
    recompute the invoice's payment_status."""
    from apps.audit.services import record_event
    from apps.purchases.models import PurchaseInvoice
    from apps.sales.models import SalesInvoice
    from apps.treasury.models import Payment, PaymentAllocation

    amount = Decimal(str(amount))
    if amount <= ZERO:
        raise ValidationError(_("Allocation amount must be positive."))
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status != Payment.Status.POSTED:
        raise ValidationError(_("Allocations are only allowed on POSTED payments (ADR-023)."))

    is_sales = isinstance(invoice, SalesInvoice)
    is_purchase = isinstance(invoice, PurchaseInvoice)
    if not (is_sales ^ is_purchase):
        raise ValidationError(_("Allocation target must be a sales or purchase invoice."))
    if is_sales and payment.direction != Payment.Direction.RECEIPT:
        raise ValidationError(_("Only a RECEIPT can be allocated to a sales invoice."))
    if is_purchase and payment.direction != Payment.Direction.PAYMENT:
        raise ValidationError(_("Only a PAYMENT can be allocated to a purchase invoice."))

    invoice = type(invoice).objects.select_for_update().get(pk=invoice.pk)
    if invoice.company_id != payment.company_id:
        raise ValidationError(_("Invoice belongs to a different company."))
    if invoice.status != "POSTED":
        raise ValidationError(_("Allocations target only POSTED invoices."))
    invoice_party = invoice.customer if is_sales else invoice.supplier
    if invoice_party.id != payment.party_id:
        raise ValidationError(_("Invoice party does not match the payment party."))

    if allocated_total_for_payment(payment) + amount > payment.amount:
        raise ValidationError(_("Allocations would exceed the payment amount."))
    if allocated_total_for_invoice(invoice) + amount > invoice.grand_total:
        raise ValidationError(_("Allocations would exceed the invoice grand total."))

    allocation = PaymentAllocation.objects.create(
        company=payment.company,
        payment=payment,
        sales_invoice=invoice if is_sales else None,
        purchase_invoice=invoice if is_purchase else None,
        amount=amount,
    )
    recompute_payment_status(invoice)
    record_event(
        action="payment.allocated",
        entity_type="PaymentAllocation",
        company=payment.company,
        user=user,
        entity_id=allocation.id,
        payment_id=str(payment.id),
        amount=str(amount),
    )
    return allocation


@transaction.atomic
def void_allocation(allocation, *, user=None, reason=""):
    """Void one ACTIVE allocation (kept for history, ADR-025) and
    recompute the target invoice's payment_status."""
    from apps.audit.services import record_event
    from apps.treasury.models import PaymentAllocation

    allocation = PaymentAllocation.objects.select_for_update().get(pk=allocation.pk)
    if allocation.status != PaymentAllocation.Status.ACTIVE:
        raise ValidationError(_("Only an ACTIVE allocation can be voided."))
    allocation.status = PaymentAllocation.Status.VOID
    allocation.voided_at = timezone.now()
    allocation.void_reason = reason
    allocation.save(update_fields=["status", "voided_at", "void_reason", "updated_at"])
    invoice = allocation.invoice
    if invoice is not None:
        recompute_payment_status(invoice)
    record_event(
        action="payment.allocation_voided",
        entity_type="PaymentAllocation",
        company=allocation.company,
        user=user,
        entity_id=allocation.id,
        reason=reason,
    )
    return allocation


def _void_allocations_of_payment(payment, *, user, reason):
    from apps.treasury.models import PaymentAllocation

    affected = []
    for allocation in PaymentAllocation.objects.filter(
        payment=payment, status=PaymentAllocation.Status.ACTIVE
    ):
        invoice = allocation.invoice
        allocation.status = PaymentAllocation.Status.VOID
        allocation.voided_at = timezone.now()
        allocation.void_reason = reason
        allocation.save(update_fields=["status", "voided_at", "void_reason", "updated_at"])
        if invoice is not None:
            affected.append(invoice)
    for invoice in affected:
        recompute_payment_status(invoice)


@transaction.atomic
def reverse_payment(payment, *, user=None, reason=""):
    """Reverse a POSTED payment: void its allocations, recompute the
    affected invoices, reverse its journal, flip it to REVERSED.

    A payment whose cheque already CLEARED or BOUNCED cannot be
    reversed: those are separate financial events with their own
    journals (a bounced cheque has already restored the receivable)."""
    from apps.accounting.services import reverse_journal_entry
    from apps.audit.services import record_event
    from apps.treasury.models import Cheque, Payment

    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.REVERSED:
        raise ValidationError(_("This payment has already been reversed."))
    if payment.status != Payment.Status.POSTED:
        raise ValidationError(_("Only a POSTED payment can be reversed."))
    cheque = payment.cheques.first()
    if cheque is not None and cheque.status in (Cheque.Status.CLEARED, Cheque.Status.BOUNCED):
        raise ValidationError(
            _("A payment whose cheque is %(status)s cannot be reversed.")
            % {"status": cheque.status}
        )
    _void_allocations_of_payment(payment, user=user, reason=reason or "payment reversed")
    if payment.journal_entry_id:
        reverse_journal_entry(entry=payment.journal_entry, user=user, reason=reason)
    payment.status = Payment.Status.REVERSED
    payment.save()
    if cheque is not None:
        _assert_cheque_transition(cheque, Cheque.Status.REVERSED)
        cheque.status = Cheque.Status.REVERSED
        cheque.save(update_fields=["status", "updated_at"])
    record_event(
        action="payment.reversed",
        entity_type="Payment",
        company=payment.company,
        user=user,
        entity_id=payment.id,
        reason=reason,
    )
    return payment


# ---------------------------------------------------------------------------
# Cheques (ADR-026)
# ---------------------------------------------------------------------------


def _get_cheque(pk):
    from apps.treasury.models import Cheque

    return Cheque.objects.select_for_update().get(pk=pk)


@transaction.atomic
def deposit_cheque(cheque, *, user=None):
    """RECEIVED -> DEPOSITED. No journal: the value still sits in the
    cheques-in-hand account until clearing."""
    from apps.treasury.models import Cheque

    cheque = _get_cheque(cheque.pk)
    if cheque.direction != Cheque.Direction.RECEIVED:
        raise ValidationError(_("Only a received cheque can be deposited."))
    _assert_cheque_transition(cheque, Cheque.Status.DEPOSITED)
    cheque.status = Cheque.Status.DEPOSITED
    cheque.save(update_fields=["status", "updated_at"])
    return cheque


@transaction.atomic
def clear_cheque(cheque, *, user=None, bank_treasury_account=None, clearing_date=None):
    """Clear a cheque.

    RECEIVED: Dr the deposit bank treasury account's GL / Cr
    cheques-in-hand (key ``cheque-clear:<id>``); ``bank_treasury_account``
    (kind BANK) is required. ISSUED: Dr cheques-payable holding account
    / Cr the GL of the bank treasury account the cheque was drawn on —
    the payment's own treasury account."""
    from apps.accounting.services import post_journal_entry
    from apps.audit.services import record_event
    from apps.treasury.models import Cheque, TreasuryAccount

    cheque = _get_cheque(cheque.pk)
    _assert_cheque_transition(cheque, Cheque.Status.CLEARED)
    if cheque.holding_account_id is None:
        raise ValidationError(_("Cheque has no holding account; its payment is not posted."))
    entry_date = clearing_date or cheque.due_date
    if cheque.direction == Cheque.Direction.RECEIVED:
        if bank_treasury_account is None:
            raise ValidationError(_("Clearing a received cheque needs a bank treasury account."))
        _validate_treasury_account(cheque.company, bank_treasury_account)
        if bank_treasury_account.kind != TreasuryAccount.Kind.BANK:
            raise ValidationError(_("Received cheques clear into a BANK treasury account."))
        bank_gl = bank_treasury_account.gl_account
        lines = [
            {"account": bank_gl, "debit": cheque.amount},
            {"account": cheque.holding_account, "credit": cheque.amount},
        ]
    else:
        payment = cheque.payment
        if payment is None:
            raise ValidationError(_("Issued cheque has no payment."))
        bank_gl = payment.treasury_account.gl_account
        lines = [
            {"account": cheque.holding_account, "debit": cheque.amount},
            {"account": bank_gl, "credit": cheque.amount},
        ]
    entry = post_journal_entry(
        company=cheque.company,
        entry_date=entry_date,
        lines=lines,
        description=f"Cheque {cheque.cheque_number} cleared",
        user=user,
        source_type="CHEQUE_CLEAR",
        source_id=str(cheque.id),
        idempotency_key=f"cheque-clear:{cheque.id}",
    )
    cheque.clearing_journal_entry = entry
    cheque.status = Cheque.Status.CLEARED
    cheque.save(update_fields=["clearing_journal_entry", "status", "updated_at"])
    record_event(
        action="cheque.cleared",
        entity_type="Cheque",
        company=cheque.company,
        user=user,
        entity_id=cheque.id,
    )
    return cheque


def _reverse_cheque_receipt_effect(cheque, *, user, journal_date, key_prefix, source_type, action):
    """Shared finance of bounce/return: undo the receipt (or issue)
    effect and void the linked payment's allocations."""
    from apps.accounting.services import post_journal_entry

    payment = cheque.payment
    if payment is None or payment.counterparty_account_id is None:
        raise ValidationError(_("Cheque payment is not posted; nothing to reverse."))
    counterparty = payment.counterparty_account
    if cheque.direction == "RECEIVED":
        lines = [
            {"account": counterparty, "debit": cheque.amount, "party": payment.party},
            {"account": cheque.holding_account, "credit": cheque.amount},
        ]
    else:
        lines = [
            {"account": cheque.holding_account, "debit": cheque.amount},
            {"account": counterparty, "credit": cheque.amount, "party": payment.party},
        ]
    entry = post_journal_entry(
        company=cheque.company,
        entry_date=journal_date,
        lines=lines,
        description=f"Cheque {cheque.cheque_number} {action}",
        user=user,
        source_type=source_type,
        source_id=str(cheque.id),
        idempotency_key=f"{key_prefix}:{cheque.id}",
    )
    _void_allocations_of_payment(payment, user=user, reason=f"cheque {action}")
    return entry


@transaction.atomic
def bounce_cheque(cheque, *, user=None, bounce_date=None):
    """Bounce a cheque: restore the counterparty balance (the party
    owes / is owed again), void the linked payment's allocations so
    invoices fall back toward UNPAID, and mark the cheque BOUNCED."""
    from apps.audit.services import record_event
    from apps.treasury.models import Cheque

    cheque = _get_cheque(cheque.pk)
    _assert_cheque_transition(cheque, Cheque.Status.BOUNCED)
    entry = _reverse_cheque_receipt_effect(
        cheque,
        user=user,
        journal_date=bounce_date or cheque.due_date,
        key_prefix="cheque-bounce",
        source_type="CHEQUE_BOUNCE",
        action="bounced",
    )
    cheque.bounce_journal_entry = entry
    cheque.status = Cheque.Status.BOUNCED
    cheque.save(update_fields=["bounce_journal_entry", "status", "updated_at"])
    record_event(
        action="cheque.bounced",
        entity_type="Cheque",
        company=cheque.company,
        user=user,
        entity_id=cheque.id,
    )
    return cheque


@transaction.atomic
def return_cheque(cheque, *, user=None, return_date=None):
    """Return a received cheque to its issuer: financially identical
    to a bounce (the money never arrived), with its own status and
    journal key so the register keeps the two events distinct."""
    from apps.audit.services import record_event
    from apps.treasury.models import Cheque

    cheque = _get_cheque(cheque.pk)
    if cheque.direction != Cheque.Direction.RECEIVED:
        raise ValidationError(_("Only a received cheque can be returned."))
    _assert_cheque_transition(cheque, Cheque.Status.RETURNED)
    entry = _reverse_cheque_receipt_effect(
        cheque,
        user=user,
        journal_date=return_date or cheque.due_date,
        key_prefix="cheque-return",
        source_type="CHEQUE_RETURN",
        action="returned",
    )
    cheque.bounce_journal_entry = entry
    cheque.status = Cheque.Status.RETURNED
    cheque.save(update_fields=["bounce_journal_entry", "status", "updated_at"])
    record_event(
        action="cheque.returned",
        entity_type="Cheque",
        company=cheque.company,
        user=user,
        entity_id=cheque.id,
    )
    return cheque
