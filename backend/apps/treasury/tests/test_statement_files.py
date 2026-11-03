"""Sprint 18 — CAMT.053 / OFX statement parsers and the generalized
import pipeline (ADR-044).

Golden parser tests assert the exact normalized rows (locator, raw
contract dict) and header metadata per format; service tests run
the parsers through ``reconciliation.import_statement_file`` and
the create-from-file service with its totals identity.
"""

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.treasury import reconciliation as recon
from apps.treasury import statement_files
from apps.treasury.models import BankStatement
from apps.treasury.tests._helpers import D, build_world
from apps.treasury.tests._statement_files import (
    CAMT_BROKEN,
    CAMT_CLEAN,
    CAMT_PLAIN,
    CAMT_TWO_STMTS,
    GARBAGE_BYTES,
    GARBAGE_HTML,
    OFX1,
    OFX2,
    OFX_BROKEN,
)

pytestmark = pytest.mark.django_db

JUN1 = date(2026, 6, 1)
JUN30 = date(2026, 6, 30)


# ---------------------------------------------------------------------------
# Detection + golden parser tests
# ---------------------------------------------------------------------------


def test_format_is_sniffed_from_content():
    assert statement_files.detect_format(CAMT_CLEAN.encode()) == "camt053"
    assert statement_files.detect_format(OFX1.encode()) == "ofx"
    assert statement_files.detect_format(OFX2.encode()) == "ofx"
    assert statement_files.detect_format(b"date,description,reference,amount\n") == "csv"
    parsed = statement_files.parse_statement_file(CAMT_CLEAN.encode())
    assert parsed.format == "camt053"


def test_camt_golden_rows_and_metadata():
    parsed = statement_files.parse_statement_file(CAMT_BROKEN.encode())
    assert parsed.format == "camt053"
    assert parsed.rows == [
        (
            1,
            {
                "date": "2026-06-01",
                "amount": "1100.00",
                "description": "Customer transfer inbound",
                "reference": "REF-A",
            },
        ),
        (
            2,
            {
                "date": "2026-06-02",
                "amount": "-300.00",
                "description": "Supplier payment by transfer",
                "reference": "REF-B",
            },
        ),
    ]
    # The broken amount is a per-transaction rejection at its index;
    # the other two entries still parse.
    assert parsed.rejected == [{"row": 3, "reason": "مبلغ 'not-a-number' قابل خواندن نیست."}]
    assert parsed.metadata == {
        "opening_balance": D("0.00"),
        "closing_balance": D("800.00"),
        "period_start": date(2026, 6, 1),
        "period_end": date(2026, 6, 15),  # fallback: entry dates
    }


def test_camt_clean_metadata_fr_to_dt_and_reference_fallbacks():
    parsed = statement_files.parse_statement_file(CAMT_CLEAN.encode())
    assert parsed.metadata == {
        "opening_balance": D("100.00"),
        "closing_balance": D("900.00"),
        "period_start": JUN1,
        "period_end": JUN30,
    }
    assert parsed.rejected == []
    first, second = [row for _, row in parsed.rows]
    assert first["reference"] == "C-1001"  # entry-level AcctSvcrRef
    assert first["description"] == "Customer transfer"  # RmtInf/Ustrd
    assert second["reference"] == "E2E-2002"  # TxDtls Refs EndToEndId
    assert second["description"] == "Supplier payment"  # AddtlNtryInf
    assert second["amount"] == "-300.00"  # DBIT signs the amount


def test_camt_without_namespace_still_parses():
    parsed = statement_files.parse_statement_file(CAMT_PLAIN.encode())
    assert parsed.format == "camt053"
    assert parsed.rows == [
        (
            1,
            {
                "date": "2026-06-05",
                "amount": "50.00",
                "description": "Plain transfer",
                "reference": "P-1",
            },
        )
    ]


def test_camt_file_with_two_statements_is_refused():
    with pytest.raises(ValidationError, match="در هر فایل یک"):
        statement_files.parse_statement_file(CAMT_TWO_STMTS.encode())


def test_ofx1_golden_rows_and_metadata():
    parsed = statement_files.parse_statement_file(OFX1.encode())
    assert parsed.format == "ofx"
    assert parsed.rejected == []
    assert parsed.rows == [
        (
            1,
            {
                # DTPOSTED 20260601103000[3:IRST]: the date is taken
                # as written; the offset must NOT shift it.
                "date": "2026-06-01",
                "amount": "1100.00",
                "description": "Customer Transfer — Invoice 44",
                "reference": "202606010001",
            },
        ),
        (
            2,
            {
                "date": "2026-06-02",
                "amount": "-300.00",
                "description": "Supplier Payment",
                "reference": "202606020001",
            },
        ),
        (
            3,
            {
                "date": "2026-06-15",
                "amount": "-50.25",
                "description": "Bank — Monthly fee",
                "reference": "202606150001",
            },
        ),
    ]
    assert parsed.metadata == {
        "opening_balance": None,  # OFX carries no opening balance
        "closing_balance": D("1749.75"),  # LEDGERBAL/BALAMT
        "period_start": JUN1,
        "period_end": JUN30,
    }


def test_ofx2_xml_golden_rows():
    parsed = statement_files.parse_statement_file(OFX2.encode())
    assert parsed.format == "ofx"
    assert [row for _, row in parsed.rows] == [
        {
            "date": "2026-06-03",
            "amount": "2500.50",
            "description": "Card Sale — POS terminal",
            "reference": "XML-0001",
        },
        {
            "date": "2026-06-04",
            "amount": "-125.00",
            "description": "Utility Bill",
            "reference": "XML-0002",
        },
    ]
    assert parsed.metadata["closing_balance"] == D("2375.50")


def test_ofx_broken_amount_is_a_per_transaction_rejection():
    parsed = statement_files.parse_statement_file(OFX_BROKEN.encode())
    assert [locator for locator, _ in parsed.rows] == [1, 3]
    assert parsed.rejected == [{"row": 2, "reason": "مبلغ 'not-a-number' قابل خواندن نیست."}]


def test_garbage_files_get_clean_file_level_refusals():
    # Well-formed text that matches no parser falls through to the
    # CSV contract and is refused exactly like a bad CSV header.
    with pytest.raises(ValidationError, match="به ستون «date» نیاز دارد"):
        statement_files.parse_statement_file(GARBAGE_HTML.encode())
    # Not text at all: the undecodable refusal class.
    with pytest.raises(statement_files.UndecodableStatementFile):
        statement_files.parse_statement_file(GARBAGE_BYTES)


# ---------------------------------------------------------------------------
# Service level: the generalized import + the create-from-file flow
# ---------------------------------------------------------------------------


def _statement(w, opening="0", closing="0"):
    return recon.create_statement(
        company=w.company,
        treasury_account=w.bank_treasury,
        start_date=JUN1,
        end_date=JUN30,
        opening_balance=D(opening),
        closing_balance=D(closing),
    )


def test_import_camt_into_existing_statement_partial():
    w = build_world()
    statement = _statement(w)
    report = recon.import_statement_file(statement, content=CAMT_BROKEN.encode())
    assert report["format"] == "camt053"
    assert report["imported"] == 2
    assert report["rejected"] == [{"row": 3, "reason": "مبلغ 'not-a-number' قابل خواندن نیست."}]
    lines = sorted(statement.lines.all(), key=lambda line: line.amount, reverse=True)
    assert [(line.amount, line.reference) for line in lines] == [
        (D("1100"), "REF-A"),
        (D("-300"), "REF-B"),
    ]


def test_import_ofx_reimport_is_all_duplicates():
    w = build_world()
    statement = _statement(w)
    first = recon.import_statement_file(statement, content=OFX1.encode())
    assert first["imported"] == 3
    assert first["rejected"] == []
    second = recon.import_statement_file(statement, content=OFX1.encode())
    assert second["imported"] == 0
    assert [item["row"] for item in second["rejected"]] == [1, 2, 3]
    assert all("از قبل وجود دارد" in item["reason"] for item in second["rejected"])
    assert statement.lines.count() == 3


def test_create_statement_from_upload_enforces_totals_identity():
    w = build_world()
    parsed = statement_files.parse_statement_file(CAMT_CLEAN.encode())
    statement, report = recon.create_statement_from_upload(
        company=w.company,
        treasury_account=w.bank_treasury,
        start_date=parsed.metadata["period_start"],
        end_date=parsed.metadata["period_end"],
        opening_balance=parsed.metadata["opening_balance"],
        closing_balance=parsed.metadata["closing_balance"],
        parsed=parsed,
    )
    assert report == {"imported": 2, "rejected": []}
    assert statement.opening_balance == D("100.00")
    assert statement.closing_balance == D("900.00")
    assert statement.lines.count() == 2

    # Tampered closing: opening + lines != closing -> refused, and
    # the rollback leaves no statement behind.
    with pytest.raises(ValidationError, match="سازگار نیستند: افتتاحیه"):
        recon.create_statement_from_upload(
            company=w.company,
            treasury_account=w.bank_treasury,
            start_date=JUN1,
            end_date=JUN30,
            opening_balance=D("100"),
            closing_balance=D("901"),
            parsed=statement_files.parse_statement_file(CAMT_CLEAN.encode()),
        )
    assert BankStatement.objects.filter(company=w.company).count() == 1


def test_create_statement_from_upload_ofx_with_user_supplied_opening():
    w = build_world()
    parsed = statement_files.parse_statement_file(OFX1.encode())
    assert parsed.metadata["opening_balance"] is None
    statement, report = recon.create_statement_from_upload(
        company=w.company,
        treasury_account=w.bank_treasury,
        start_date=parsed.metadata["period_start"],
        end_date=parsed.metadata["period_end"],
        opening_balance=D("1000"),  # OFX has none: the user supplies it
        closing_balance=parsed.metadata["closing_balance"],
        parsed=parsed,
    )
    assert report == {"imported": 3, "rejected": []}
    assert statement.closing_balance == D("1749.75")
    assert statement.lines.count() == 3
