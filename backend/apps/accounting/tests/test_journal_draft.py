"""Sprint 12 — manual journal draft services (ADR-039).

``create_journal_draft`` / ``post_journal_draft`` are the thinnest
service functions the data-entry UI needed: the accounting app
previously only exposed create-and-post atomically. Drafts must pass
the same §6.3 validation as a posting, must not move any balance
until posted, and posting must re-check the open-period gate.
"""

import pytest
from django.core.exceptions import ValidationError

from apps.accounting import reporting, services
from apps.accounting.models import JournalEntry
from apps.treasury.tests._helpers import DAY, D, build_world

pytestmark = pytest.mark.django_db


def _lines(w, debit="500", credit="500"):
    return [
        {"account": w.cash, "debit": D(debit), "credit": D("0")},
        {"account": w.revenue, "debit": D("0"), "credit": D(credit)},
    ]


def _tb_total(w):
    return reporting.trial_balance(w.company)["total_debit"]


def test_draft_does_not_move_trial_balance():
    w = build_world()
    entry = services.create_journal_draft(
        company=w.company, entry_date=DAY, lines=_lines(w), description="manual"
    )
    assert entry.status == JournalEntry.Status.DRAFT
    assert entry.source_type == "MANUAL"
    assert _tb_total(w) == D("0")


def test_post_draft_moves_trial_balance():
    w = build_world()
    entry = services.create_journal_draft(company=w.company, entry_date=DAY, lines=_lines(w))
    services.post_journal_draft(entry)
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.POSTED
    tb = reporting.trial_balance(w.company)
    assert tb["total_debit"] == D("500")
    assert tb["total_credit"] == D("500")
    assert tb["is_balanced"]


def test_unbalanced_draft_rejected_and_nothing_persisted():
    w = build_world()
    with pytest.raises(ValidationError):
        services.create_journal_draft(
            company=w.company, entry_date=DAY, lines=_lines(w, credit="400")
        )
    assert JournalEntry.objects.filter(company=w.company).count() == 0


def test_two_sided_line_rejected():
    w = build_world()
    bad = [
        {"account": w.cash, "debit": D("500"), "credit": D("500")},
        {"account": w.revenue, "debit": D("0"), "credit": D("500")},
    ]
    with pytest.raises(ValidationError):
        services.create_journal_draft(company=w.company, entry_date=DAY, lines=bad)
    assert JournalEntry.objects.filter(company=w.company).count() == 0


def test_cross_company_account_rejected():
    w = build_world()
    other = build_world(company_name="Other Co")
    lines = [
        {"account": other.cash, "debit": D("500"), "credit": D("0")},
        {"account": w.revenue, "debit": D("0"), "credit": D("500")},
    ]
    with pytest.raises(ValidationError):
        services.create_journal_draft(company=w.company, entry_date=DAY, lines=lines)
    assert JournalEntry.objects.filter(company=w.company).count() == 0


def test_duplicate_idempotency_key_rejected():
    w = build_world()
    services.create_journal_draft(
        company=w.company, entry_date=DAY, lines=_lines(w), idempotency_key="form-1"
    )
    with pytest.raises(ValidationError):
        services.create_journal_draft(
            company=w.company, entry_date=DAY, lines=_lines(w), idempotency_key="form-1"
        )
    assert JournalEntry.objects.filter(company=w.company).count() == 1


def test_post_into_closed_period_rejected():
    w = build_world(period_status="CLOSED")
    entry = services.create_journal_draft(company=w.company, entry_date=DAY, lines=_lines(w))
    with pytest.raises(ValidationError):
        services.post_journal_draft(entry)
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.DRAFT
    assert _tb_total(w) == D("0")


def test_double_post_is_idempotent():
    w = build_world()
    entry = services.create_journal_draft(company=w.company, entry_date=DAY, lines=_lines(w))
    services.post_journal_draft(entry)
    again = services.post_journal_draft(entry)
    assert again.status == JournalEntry.Status.POSTED
    assert _tb_total(w) == D("500")


def test_reversed_entry_cannot_be_posted():
    w = build_world()
    entry = services.create_journal_draft(company=w.company, entry_date=DAY, lines=_lines(w))
    services.post_journal_draft(entry)
    services.reverse_journal_entry(entry=entry, reason="mistake")
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.REVERSED
    with pytest.raises(ValidationError):
        services.post_journal_draft(entry)
