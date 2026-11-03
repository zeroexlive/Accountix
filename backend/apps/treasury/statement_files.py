"""Statement file parsers (Sprint 18, ADR-044).

One pipeline, many parsers. Every supported bank-statement file
format is parsed into the SAME normalized shape the Sprint 14 CSV
importer defined: raw row dicts in the CSV contract shape
(``{date, description, reference, amount}`` as strings, amount
signed from the bank's perspective) in file order, each tagged with
a **locator** used in error reports — for CSV the physical line
number (the header is line 1), for the XML formats the 1-based
transaction index in file order. A parser also reports the rows it
could not even normalize (``rejected``, in the same locator space
and with the same reason strings the CSV validator uses) and
optional header metadata (opening/closing balances, period) that
the statement-create flow uses to prefill the header form.

``treasury.reconciliation`` validates and imports the rows exactly
as it always has (period bounds, zero amount, lengths, duplicate
triple). The parsers here know nothing about statements or the
database.

Supported formats, detected by CONTENT (the filename extension is
never consulted):

- CSV — the Sprint 14 contract (header ``date,description,
  reference,amount`` or a ``debit`` + ``credit`` pair).
- CAMT.053 (ISO 20022) — parsed with the stdlib ElementTree,
  namespace-agnostic (elements are matched by local name, so
  camt.053.001.02/.08/... all parse). One file must contain exactly
  one ``<Stmt>``.
- OFX 1.x (SGML) and OFX 2.x (XML) — a tolerant hand parser for the
  bank-statement subset. ``ofxparse`` was evaluated and rejected
  (ADR-044): it converts posting timestamps to UTC, which can
  shift the calendar date, and it aborts the whole file on the
  first bad transaction instead of reporting it per-row.
"""

import csv
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError

EMPTY_METADATA: dict[str, Any] = {
    "opening_balance": None,
    "closing_balance": None,
    "period_start": None,
    "period_end": None,
}


class StatementFileError(ValidationError):
    """A file-level refusal: the upload cannot be imported at all
    (bad header, wrong shape, several statements in one file, ...).
    Row-level problems are reported per row instead."""


class UndecodableStatementFile(StatementFileError):
    """The bytes are not decodable text in a supported encoding."""


@dataclass
class ParsedStatementFile:
    """The normalized output of every statement parser."""

    format: str  # "csv" | "camt053" | "ofx"
    rows: list = field(default_factory=list)  # [(locator, raw row dict)]
    rejected: list = field(default_factory=list)  # [{"row": loc, "reason": str}]
    metadata: dict = field(default_factory=lambda: dict(EMPTY_METADATA))


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _local_name(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _is_camt053(root):
    if "camt.053" in root.tag:
        return True
    return any(_local_name(el.tag) == "BkToCstmrStmt" for el in root.iter())


def detect_format(content: bytes) -> str:
    """Sniff the format from the content: OFX markers first (an OFX
    2.x file is XML, so OFX wins over the XML checks), then a CAMT
    root check, and anything else is treated as CSV — whose header
    validation produces the clean file-level refusal for garbage."""
    head = content[:8192]
    if b"OFXHEADER" in head or b"<OFX" in head:
        return "ofx"
    body = content[3:] if content.startswith(b"\xef\xbb\xbf") else content
    if body.lstrip()[:1] == b"<":
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            root = None
        if root is not None:
            if _local_name(root.tag) == "OFX":
                return "ofx"
            if _local_name(root.tag) == "Document" and _is_camt053(root):
                return "camt053"
    return "csv"


def parse_statement_file(content: bytes) -> ParsedStatementFile:
    fmt = detect_format(content)
    if fmt == "ofx":
        return parse_ofx(content)
    if fmt == "camt053":
        return parse_camt053(content)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UndecodableStatementFile("The statement file is not valid UTF-8 text.") from None
    return parse_csv_text(text)


# ---------------------------------------------------------------------------
# CSV (the Sprint 14 contract, moved verbatim from reconciliation)
# ---------------------------------------------------------------------------


def parse_csv_text(text: str) -> ParsedStatementFile:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise StatementFileError("The CSV file is empty or has no header row.")
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    fields = set(reader.fieldnames)
    if "date" not in fields:
        raise StatementFileError("The CSV needs a 'date' column.")
    if "amount" not in fields and not {"debit", "credit"} <= fields:
        raise StatementFileError("The CSV needs an 'amount' column (or 'debit' + 'credit').")
    rows = []
    for row in reader:
        rows.append(
            (
                reader.line_num,
                {key.strip().lower(): value for key, value in row.items() if key},
            )
        )
    return ParsedStatementFile(format="csv", rows=rows)


# ---------------------------------------------------------------------------
# CAMT.053
# ---------------------------------------------------------------------------


def _children(element, name):
    return [child for child in element if _local_name(child.tag) == name]


def _first(element, name):
    for child in element:
        if _local_name(child.tag) == name:
            return child
    return None


def _descendants(element, name):
    return [el for el in element.iter() if _local_name(el.tag) == name]


def _text(element):
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _parse_iso_date(raw):
    """An ISO date, or the date part of an ISO datetime; None if the
    text is neither."""
    try:
        return datetime.strptime((raw or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _camt_date_element(element):
    """Text of a camt date holder: the element's own text, or its
    <Dt>/<DtTm> child's."""
    if element is None:
        return ""
    for name in ("Dt", "DtTm"):
        child = _first(element, name)
        if child is not None:
            return _text(child)
    return _text(element)


def _camt_balance_amount(balance_el):
    amount_el = _first(balance_el, "Amt")
    raw = _text(amount_el)
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise StatementFileError(f"Unparseable balance amount {raw!r} in the CAMT file.") from None
    if _text(_first(balance_el, "CdtDbtInd")) == "DBIT":
        amount = -abs(amount)
    else:
        amount = abs(amount)
    return amount


def _camt_reference(entry):
    reference = _text(_first(entry, "AcctSvcrRef"))
    if reference:
        return reference
    tx_details = _descendants(entry, "TxDtls")
    for tx in tx_details:
        refs = _first(tx, "Refs")
        if refs is not None:
            reference = _text(_first(refs, "AcctSvcrRef"))
            if reference:
                return reference
    for tx in tx_details:
        refs = _first(tx, "Refs")
        if refs is not None:
            reference = _text(_first(refs, "EndToEndId"))
            # "NOTPROVIDED" is a placeholder, not a reference: using
            # it would make unrelated entries false duplicates.
            if reference and reference != "NOTPROVIDED":
                return reference
    return ""


def _camt_description(entry):
    ustrd = " ".join(
        text for text in (_text(el) for el in _descendants(entry, "Ustrd")) if text
    ).strip()
    if ustrd:
        return ustrd
    additional = _text(next(iter(_descendants(entry, "AddtlNtryInf")), None))
    if additional:
        return additional
    for code_el in _descendants(entry, "BkTxCd"):
        domain = _first(code_el, "Domn")
        if domain is None:
            continue
        parts = [_text(_first(domain, "Cd"))]
        family = _first(domain, "Fmly")
        if family is not None:
            parts.append(_text(_first(family, "Cd")))
            parts.append(_text(_first(family, "SubFmlyCd")))
        joined = "/".join(part for part in parts if part)
        if joined:
            return joined
    return ""


def parse_camt053(content: bytes) -> ParsedStatementFile:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise StatementFileError("The CAMT file is not well-formed XML.") from None
    statements = []
    for container in _descendants(root, "BkToCstmrStmt"):
        statements.extend(_children(container, "Stmt"))
    if not statements:
        raise StatementFileError("No bank statement (BkToCstmrStmt) found in the CAMT file.")
    if len(statements) > 1:
        raise StatementFileError(
            f"The file contains {len(statements)} statements; import one statement per file."
        )
    stmt = statements[0]

    metadata = dict(EMPTY_METADATA)
    for balance in _children(stmt, "Bal"):
        type_el = _first(balance, "Tp")
        code = ""
        if type_el is not None:
            code_or_prtry = _first(type_el, "CdOrPrtry")
            if code_or_prtry is not None:
                code = _text(_first(code_or_prtry, "Cd"))
        if code == "OPBD":
            metadata["opening_balance"] = _camt_balance_amount(balance)
        elif code == "CLBD":
            metadata["closing_balance"] = _camt_balance_amount(balance)

    rows = []
    rejected = []
    entry_dates = []
    for index, entry in enumerate(_children(stmt, "Ntry"), start=1):
        raw_date = _camt_date_element(_first(entry, "BookgDt"))
        line_date = _parse_iso_date(raw_date)
        if line_date is None:
            rejected.append(
                {
                    "row": index,
                    "reason": f"Unparseable date {raw_date!r} (expected YYYY-MM-DD).",
                }
            )
            continue
        entry_dates.append(line_date)
        amount_el = _first(entry, "Amt")
        if amount_el is None:
            rejected.append({"row": index, "reason": "Missing amount."})
            continue
        raw_amount = _text(amount_el)
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            rejected.append({"row": index, "reason": f"Unparseable amount {raw_amount!r}."})
            continue
        if _text(_first(entry, "CdtDbtInd")) == "DBIT":
            amount = -abs(amount)
        else:
            amount = abs(amount)
        rows.append(
            (
                index,
                {
                    "date": line_date.isoformat(),
                    "amount": str(amount),
                    "description": _camt_description(entry),
                    "reference": _camt_reference(entry),
                },
            )
        )

    period = _first(stmt, "FrToDt")
    if period is not None:
        metadata["period_start"] = _parse_iso_date(_camt_date_element(_first(period, "FrDt")))
        metadata["period_end"] = _parse_iso_date(_camt_date_element(_first(period, "ToDt")))
    if metadata["period_start"] is None and entry_dates:
        metadata["period_start"] = min(entry_dates)
    if metadata["period_end"] is None and entry_dates:
        metadata["period_end"] = max(entry_dates)
    return ParsedStatementFile(format="camt053", rows=rows, rejected=rejected, metadata=metadata)


# ---------------------------------------------------------------------------
# OFX 1.x (SGML) + 2.x (XML) — tolerant subset parser
# ---------------------------------------------------------------------------

_OFX_DATE_RE = re.compile(r"^\s*(\d{4})(\d{2})(\d{2})")


def _ofx_date(raw):
    """The calendar date AS WRITTEN in an OFX datetime: the leading
    YYYYMMDD digits; the time and the [offset:tz] suffix are ignored
    for the date (ADR-044). None when the value has no valid date."""
    match = _OFX_DATE_RE.match(raw or "")
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _ofx_leaf(block, name):
    match = re.search(rf"<{name}>([^<]*)", block, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _ofx_block(text, name):
    match = re.search(rf"<{name}>(.*?)</{name}\s*>", text, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else None


def parse_ofx(content: bytes) -> ParsedStatementFile:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # OFX 1.x files commonly declare CHARSET:1252; latin-1 maps
        # every byte, so the ASCII structure always survives.
        text = content.decode("latin-1")
    tran_list = _ofx_block(text, "BANKTRANLIST")
    if tran_list is None:
        raise StatementFileError("No bank transaction list (BANKTRANLIST) found in the OFX file.")

    metadata = dict(EMPTY_METADATA)
    header = tran_list.split("<STMTTRN>", 1)[0]
    metadata["period_start"] = _ofx_date(_ofx_leaf(header, "DTSTART"))
    metadata["period_end"] = _ofx_date(_ofx_leaf(header, "DTEND"))
    ledger = _ofx_block(text, "LEDGERBAL")
    if ledger is not None:
        raw_balance = _ofx_leaf(ledger, "BALAMT")
        if raw_balance:
            try:
                metadata["closing_balance"] = Decimal(raw_balance)
            except InvalidOperation:
                raise StatementFileError(
                    f"Unparseable closing balance (LEDGERBAL) {raw_balance!r} in the OFX file."
                ) from None
        if metadata["period_end"] is None:
            metadata["period_end"] = _ofx_date(_ofx_leaf(ledger, "DTASOF"))
    # OFX carries no opening balance; the chaining prefill or the
    # user supplies it, exactly as with CSV.

    rows = []
    rejected = []
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN\s*>", tran_list, re.IGNORECASE | re.DOTALL)
    for index, block in enumerate(blocks, start=1):
        raw_date = _ofx_leaf(block, "DTPOSTED")
        line_date = _ofx_date(raw_date)
        if line_date is None:
            rejected.append(
                {
                    "row": index,
                    "reason": f"Unparseable date {raw_date!r} (expected YYYY-MM-DD).",
                }
            )
            continue
        raw_amount = _ofx_leaf(block, "TRNAMT")
        if not raw_amount:
            rejected.append({"row": index, "reason": "Missing amount."})
            continue
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            rejected.append({"row": index, "reason": f"Unparseable amount {raw_amount!r}."})
            continue
        name = _ofx_leaf(block, "NAME")
        memo = _ofx_leaf(block, "MEMO")
        if name and memo:
            description = f"{name} — {memo}"
        else:
            description = name or memo
        rows.append(
            (
                index,
                {
                    "date": line_date.isoformat(),
                    "amount": str(amount),
                    "description": description,
                    "reference": _ofx_leaf(block, "FITID"),
                },
            )
        )
    return ParsedStatementFile(format="ofx", rows=rows, rejected=rejected, metadata=metadata)


# ---------------------------------------------------------------------------
# Session stash (the create-from-file two-phase flow)
# ---------------------------------------------------------------------------


def parsed_to_stash(parsed: ParsedStatementFile, *, filename, account_id, company_id):
    """JSON-safe serialization of a parsed file, so the create view
    can prefill the header form in one request and consume the rows
    when the user confirms the create form in the next."""
    metadata = parsed.metadata
    return {
        "format": parsed.format,
        "filename": filename,
        "account_id": account_id,
        "company_id": company_id,
        "rows": [{"row": locator, **row} for locator, row in parsed.rows],
        "rejected": parsed.rejected,
        "metadata": {
            "opening_balance": (
                str(metadata["opening_balance"])
                if metadata.get("opening_balance") is not None
                else None
            ),
            "closing_balance": (
                str(metadata["closing_balance"])
                if metadata.get("closing_balance") is not None
                else None
            ),
            "period_start": (
                metadata["period_start"].isoformat()
                if metadata.get("period_start") is not None
                else None
            ),
            "period_end": (
                metadata["period_end"].isoformat()
                if metadata.get("period_end") is not None
                else None
            ),
        },
    }


def parsed_from_stash(data: dict) -> ParsedStatementFile:
    metadata = data.get("metadata") or {}

    def _decimal(key):
        raw = metadata.get(key)
        return Decimal(raw) if raw is not None else None

    def _date(key):
        raw = metadata.get(key)
        return date.fromisoformat(raw) if raw is not None else None

    return ParsedStatementFile(
        format=data["format"],
        rows=[
            (item["row"], {key: value for key, value in item.items() if key != "row"})
            for item in data.get("rows", [])
        ],
        rejected=[
            {"row": item["row"], "reason": item["reason"]} for item in data.get("rejected", [])
        ],
        metadata={
            "opening_balance": _decimal("opening_balance"),
            "closing_balance": _decimal("closing_balance"),
            "period_start": _date("period_start"),
            "period_end": _date("period_end"),
        },
    )
