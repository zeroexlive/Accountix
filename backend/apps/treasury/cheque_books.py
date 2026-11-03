"""Cheque book services (Sprint 15, ADR-042).

A cheque book is the inventory of physical leaves of ONE bank
treasury account, for ISSUED cheques only. The rules enforced here:

- Leaf numbers are unique per treasury account across all of its
  books (a database constraint backs this), so two books of one
  account can never overlap.
- Number generation is deliberately simple: the trailing run of
  digits of the first number is the counter; it increments by one,
  zero-padded to the counter's original width (and may outgrow it:
  "999" is followed by "1000"). A first number with no trailing
  digits can only open a one-leaf book.
- A leaf is consumed exactly once — inside ``create_payment`` when an
  outgoing CHEQUE payment names it. Consumption is opt-in: payments
  that pass no leaf behave exactly as before books existed.
- Nothing resurrects a USED leaf. Payment reversal and issued-cheque
  bounce leave it USED: the physical leaf left the book, and the
  register keeps that fact. An UNUSED leaf can be voided (damaged /
  misprinted leaf); a USED or VOID leaf cannot change state.
"""

import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _

MAX_LEAF_COUNT = 1000

_TRAILING_DIGITS = re.compile(r"^(.*?)(\d+)$")


def generate_leaf_numbers(first_number, leaf_count):
    """The leaf numbers of a book, in order. ``first_number`` is the
    printed identifier of the first leaf; its trailing digit run is
    the sequential counter (prefix preserved, width preserved)."""
    first_number = (first_number or "").strip()
    if not first_number:
        raise ValidationError(_("A cheque book needs a first leaf number."))
    match = _TRAILING_DIGITS.match(first_number)
    if match is None:
        if leaf_count == 1:
            return [first_number]
        raise ValidationError(
            _(
                "The first leaf number must end with digits so the following "
                "leaves can be numbered (got %(number)r)."
            )
            % {"number": first_number}
        )
    prefix, digits = match.groups()
    width = len(digits)
    start = int(digits)
    return [f"{prefix}{start + offset:0{width}d}" for offset in range(leaf_count)]


def _validate_book_account(company, treasury_account):
    from apps.treasury.models import TreasuryAccount

    if treasury_account is None or treasury_account.company_id != company.id:
        raise ValidationError(_("Treasury account belongs to a different company (or is missing)."))
    if treasury_account.kind != TreasuryAccount.Kind.BANK:
        raise ValidationError(_("Cheque books belong to BANK treasury accounts only."))
    if not treasury_account.is_active:
        raise ValidationError(_("Treasury account is inactive."))
    return treasury_account


@transaction.atomic
def create_cheque_book(*, company, treasury_account, first_number, leaf_count, label="", user=None):
    """Create a book and all of its leaves in one transaction.

    Fails cleanly, naming the collision, if any generated number
    already exists on a leaf of the same account."""
    from apps.audit.services import record_event
    from apps.treasury.models import ChequeBook, ChequeLeaf

    _validate_book_account(company, treasury_account)
    try:
        leaf_count = int(leaf_count)
    except (TypeError, ValueError):
        raise ValidationError(_("Leaf count must be a whole number.")) from None
    if leaf_count <= 0:
        raise ValidationError(_("A cheque book needs at least one leaf."))
    if leaf_count > MAX_LEAF_COUNT:
        raise ValidationError(
            _("A cheque book cannot have more than %(max)s leaves.") % {"max": MAX_LEAF_COUNT}
        )
    numbers = generate_leaf_numbers(first_number, leaf_count)
    existing = (
        ChequeLeaf.objects.filter(treasury_account=treasury_account, number__in=numbers)
        .order_by("number")
        .first()
    )
    if existing is not None:
        raise ValidationError(
            _(
                "Leaf number %(number)s already exists for this bank account "
                "(book %(book)s); cheque book ranges cannot overlap."
            )
            % {"number": existing.number, "book": existing.book}
        )
    book = ChequeBook.objects.create(
        company=company,
        treasury_account=treasury_account,
        label=(label or "").strip(),
        first_number=numbers[0],
        leaf_count=leaf_count,
    )
    ChequeLeaf.objects.bulk_create(
        ChequeLeaf(
            company=company,
            treasury_account=treasury_account,
            book=book,
            number=number,
            position=position,
        )
        for position, number in enumerate(numbers)
    )
    record_event(
        action="cheque_book.created",
        entity_type="ChequeBook",
        company=company,
        user=user,
        entity_id=book.id,
        treasury_account_id=str(treasury_account.id),
        first_number=numbers[0],
        last_number=numbers[-1],
        leaf_count=str(leaf_count),
    )
    return book


@transaction.atomic
def void_leaf(leaf, *, user=None):
    """Void an UNUSED leaf (damaged / misprinted). USED leaves are the
    register of paper that left the book and can never be voided."""
    from apps.audit.services import record_event
    from apps.treasury.models import ChequeLeaf

    leaf = ChequeLeaf.objects.select_for_update().get(pk=leaf.pk)
    if leaf.status != ChequeLeaf.Status.UNUSED:
        raise ValidationError(
            _("Only an UNUSED leaf can be voided (this leaf is %(status)s).")
            % {"status": leaf.status}
        )
    leaf.status = ChequeLeaf.Status.VOID
    leaf.save(update_fields=["status", "updated_at"])
    record_event(
        action="cheque_leaf.voided",
        entity_type="ChequeLeaf",
        company=leaf.company,
        user=user,
        entity_id=leaf.id,
        book_id=str(leaf.book_id),
        number=leaf.number,
    )
    return leaf


def consume_leaf(leaf, *, company, treasury_account):
    """Validate a leaf offered to ``create_payment`` and lock it for
    consumption. Returns the locked leaf (status still UNUSED; the
    caller flips it once the cheque row exists)."""
    from apps.treasury.models import ChequeLeaf

    leaf = ChequeLeaf.objects.select_for_update().get(pk=leaf.pk)
    if leaf.company_id != company.id:
        raise ValidationError(_("The cheque leaf belongs to a different company."))
    if leaf.treasury_account_id != treasury_account.id:
        raise ValidationError(
            _("The cheque leaf belongs to a different bank account than the payment's.")
        )
    if leaf.status != ChequeLeaf.Status.UNUSED:
        raise ValidationError(
            _("Cheque leaf %(number)s is %(status)s, not UNUSED.")
            % {"number": leaf.number, "status": leaf.status}
        )
    return leaf


def cheque_books_with_counts(company=None, treasury_account=None):
    """Cheque books annotated with derived leaf counts
    (unused/used/void + total) — one query, no N+1."""
    from apps.treasury.models import ChequeBook, ChequeLeaf

    qs = ChequeBook.objects.select_related("treasury_account", "company").annotate(
        unused_count=Count("leaves", filter=Q(leaves__status=ChequeLeaf.Status.UNUSED)),
        used_count=Count("leaves", filter=Q(leaves__status=ChequeLeaf.Status.USED)),
        void_count=Count("leaves", filter=Q(leaves__status=ChequeLeaf.Status.VOID)),
        total_count=Count("leaves"),
    )
    if company is not None:
        qs = qs.filter(company=company)
    if treasury_account is not None:
        qs = qs.filter(treasury_account=treasury_account)
    return qs


def book_counts(book):
    """Derived (unused, used, void) counts of one book."""
    from apps.treasury.models import ChequeLeaf

    rows = ChequeLeaf.objects.filter(book=book).values("status").annotate(n=Count("id"))
    counts = {row["status"]: row["n"] for row in rows}
    return (
        counts.get(ChequeLeaf.Status.UNUSED, 0),
        counts.get(ChequeLeaf.Status.USED, 0),
        counts.get(ChequeLeaf.Status.VOID, 0),
    )
