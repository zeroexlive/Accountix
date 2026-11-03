from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounting.models import JournalLine
from apps.core.access import resolve_scoped_company, user_company_ids
from apps.core.forms import add_service_errors
from apps.core.pagination import apply_date_range, paginate
from apps.treasury import cheque_books, reconciliation, reporting, services, statement_files
from apps.treasury.forms import (
    AllocationForm,
    BankStatementForm,
    BankStatementLineForm,
    ChequeBookForm,
    ChequeClearForm,
    PaymentForm,
    PaymentPostForm,
    StatementFilePreviewForm,
    StatementImportForm,
    StatementMatchForm,
    TreasuryAccountForm,
)
from apps.treasury.models import (
    BankStatement,
    BankStatementLine,
    Cheque,
    ChequeBook,
    ChequeLeaf,
    Payment,
    PaymentAllocation,
    TreasuryAccount,
)


@login_required
def treasury_account_list(request):
    accounts = TreasuryAccount.objects.filter(
        company_id__in=user_company_ids(request.user)
    ).select_related("company", "gl_account")
    rows = [
        {
            "account": account,
            "balance": reporting.treasury_account_balance(account.company, account),
        }
        for account in accounts
    ]
    return render(request, "treasury/account_list.html", {"rows": rows})


@login_required
def payment_list(request):
    payments = (
        Payment.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "party", "treasury_account")
        .order_by("-payment_date", "-created_at")
    )
    if request.GET.get("status"):
        payments = payments.filter(status=request.GET["status"])
    if request.GET.get("method"):
        payments = payments.filter(method=request.GET["method"])
    payments = apply_date_range(payments, request.GET, "payment_date")
    page_obj, filter_query = paginate(request, payments)
    return render(
        request,
        "treasury/payment_list.html",
        {
            "payments": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": Payment.Status.choices,
            "methods": Payment.Method.choices,
        },
    )


@login_required
def cheque_list(request):
    cheques = (
        Cheque.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "payment__party")
        .order_by("due_date")
    )
    if request.GET.get("status"):
        cheques = cheques.filter(status=request.GET["status"])
    if request.GET.get("direction"):
        cheques = cheques.filter(direction=request.GET["direction"])
    cheques = apply_date_range(cheques, request.GET, "due_date")
    # apply_date_range uses date_from/date_to on due_date; treasury uses it as due range.
    page_obj, filter_query = paginate(request, cheques)
    return render(
        request,
        "treasury/cheque_list.html",
        {
            "cheques": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": Cheque.Status.choices,
            "directions": Cheque.Direction.choices,
        },
    )


@login_required
def treasury_account_create(request):
    companies, company = resolve_scoped_company(request)
    form = TreasuryAccountForm(request.POST or None, company=company, companies=companies)
    if request.method == "POST" and company is not None and form.is_valid():
        try:
            services.create_treasury_account(
                company=company,
                kind=form.cleaned_data["kind"],
                name=form.cleaned_data["name"],
                gl_account=form.cleaned_data["gl_account"],
                bank_name=form.cleaned_data["bank_name"],
                account_number=form.cleaned_data["account_number"],
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "حساب خزانه ایجاد شد.")
            return redirect("treasury_account_list")
    return render(
        request,
        "treasury/account_form.html",
        {"form": form, "companies": companies, "company": company},
    )


@login_required
def payment_create(request):
    companies, company = resolve_scoped_company(request)
    direction = request.POST.get("direction") or request.GET.get("direction") or None
    form = PaymentForm(
        request.POST or None, company=company, companies=companies, direction=direction
    )
    if request.method == "POST" and company is not None and form.is_valid():
        data = form.cleaned_data
        cheque = None
        if data["method"] == Payment.Method.CHEQUE:
            cheque = {
                "bank_name": data["cheque_bank_name"],
                "cheque_number": data["cheque_number"],
                "sayad_id": data["sayad_id"],
                "issue_date": data["cheque_issue_date"],
                "due_date": data["cheque_due_date"],
            }
        leaf = None
        leaf_resolved = True
        if data.get("leaf"):
            leaf = ChequeLeaf.objects.filter(pk=data["leaf"], company=company).first()
            if leaf is None:
                form.add_error("leaf", "برگ دفترچه انتخاب‌شده یافت نشد.")
                leaf_resolved = False
        if leaf_resolved:
            try:
                payment = services.create_payment(
                    company=company,
                    direction=data["direction"],
                    party=data["party"],
                    treasury_account=data["treasury_account"],
                    amount=data["amount"],
                    payment_date=data["payment_date"],
                    method=data["method"],
                    reference=data["reference"],
                    description=data["description"],
                    cheque=cheque,
                    leaf=leaf,
                )
            except ValidationError as exc:
                add_service_errors(form, exc)
            else:
                messages.success(request, "دریافت/پرداخت به‌صورت پیش‌نویس ایجاد شد.")
                return redirect("payment_detail", pk=payment.pk)
    return render(
        request,
        "treasury/payment_form.html",
        {"form": form, "companies": companies, "company": company},
    )


def _payment_open_items(payment):
    """Open invoices of the payment's party that this payment may be
    allocated to (receipts → sales invoices, payments → purchases)."""
    items = reporting.open_items(payment.company, party=payment.party)
    wanted = "SALES" if payment.direction == Payment.Direction.RECEIPT else "PURCHASE"
    return [item for item in items if item["kind"] == wanted]


def _payment_detail_context(payment, post_form=None, allocation_form=None):
    context = {
        "payment": payment,
        "allocations": payment.allocations.select_related(
            "sales_invoice", "purchase_invoice"
        ).all(),
        "cheque": payment.cheques.first(),
        "allocated_total": services.allocated_total_for_payment(payment),
        "unallocated": payment.amount - services.allocated_total_for_payment(payment),
    }
    if payment.status == Payment.Status.DRAFT:
        context["post_form"] = post_form or PaymentPostForm(payment=payment)
    if payment.status == Payment.Status.POSTED:
        items = _payment_open_items(payment)
        form = allocation_form or AllocationForm(items=items)
        context["open_items"] = items
        context["allocation_form"] = form
        context["allocation_rows"] = [
            {"item": item, "field": form[f"amount_{idx}"]} for idx, item in enumerate(items)
        ]
    return context


@login_required
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("company", "party", "treasury_account"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "treasury/payment_detail.html", _payment_detail_context(payment))


@login_required
@require_POST
def payment_post(request, pk):
    payment = get_object_or_404(Payment, pk=pk, company_id__in=user_company_ids(request.user))
    form = PaymentPostForm(request.POST, payment=payment)
    if form.is_valid():
        gl_accounts = {k: v for k, v in form.cleaned_data.items() if v is not None}
        try:
            services.post_payment(payment, user=request.user, gl_accounts=gl_accounts)
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "دریافت/پرداخت ثبت نهایی شد.")
            return redirect("payment_detail", pk=payment.pk)
    payment.refresh_from_db()
    return render(
        request, "treasury/payment_detail.html", _payment_detail_context(payment, post_form=form)
    )


@login_required
@require_POST
def payment_allocate(request, pk):
    payment = get_object_or_404(Payment, pk=pk, company_id__in=user_company_ids(request.user))
    items = _payment_open_items(payment)
    form = AllocationForm(request.POST, items=items)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("payment_detail", pk=payment.pk)
    allocated_any = False
    for idx, item in enumerate(items):
        amount = form.cleaned_data.get(f"amount_{idx}")
        if not amount:
            continue
        try:
            services.allocate_payment(payment, item["invoice"], amount, user=request.user)
            allocated_any = True
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, f"{item['invoice'].invoice_number}: {message}")
    if allocated_any:
        messages.success(request, "تخصیص‌ها ثبت شد و وضعیت پرداخت فاکتورها به‌روز شد.")
    return redirect("payment_detail", pk=payment.pk)


@login_required
@require_POST
def allocation_void(request, pk, alloc_pk):
    payment = get_object_or_404(Payment, pk=pk, company_id__in=user_company_ids(request.user))
    allocation = get_object_or_404(PaymentAllocation, pk=alloc_pk, payment=payment)
    try:
        services.void_allocation(
            allocation, user=request.user, reason=request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "تخصیص باطل شد.")
    return redirect("payment_detail", pk=payment.pk)


@login_required
@require_POST
def payment_reverse(request, pk):
    payment = get_object_or_404(Payment, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.reverse_payment(payment, user=request.user, reason=request.POST.get("reason", ""))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "دریافت/پرداخت برگشت خورد.")
    return redirect("payment_detail", pk=payment.pk)


def _action_date(request, field_name):
    """Parse an optional action date (clearing/bounce/return) from POST."""
    raw = request.POST.get(field_name)
    if not raw:
        return None
    try:
        return django_forms.DateField().clean(raw)
    except ValidationError:
        return "INVALID"


@login_required
def cheque_detail(request, pk):
    cheque = get_object_or_404(
        Cheque.objects.select_related("company", "payment", "payment__party", "holding_account"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    clear_form = ChequeClearForm(company=cheque.company)
    return render(
        request,
        "treasury/cheque_detail.html",
        {"cheque": cheque, "clear_form": clear_form, "leaf": getattr(cheque, "leaf", None)},
    )


@login_required
@require_POST
def cheque_deposit(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.deposit_cheque(cheque, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "چک به بانک واگذار شد.")
    return redirect("cheque_detail", pk=cheque.pk)


@login_required
@require_POST
def cheque_clear(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company_id__in=user_company_ids(request.user))
    clearing_date = _action_date(request, "clearing_date")
    if clearing_date == "INVALID":
        messages.error(request, "تاریخ وصول معتبر نیست.")
        return redirect("cheque_detail", pk=cheque.pk)
    bank_account = None
    if cheque.direction == Cheque.Direction.RECEIVED:
        form = ChequeClearForm(request.POST, company=cheque.company)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect("cheque_detail", pk=cheque.pk)
        bank_account = form.cleaned_data["bank_treasury_account"]
        clearing_date = form.cleaned_data["clearing_date"] or clearing_date
    try:
        services.clear_cheque(
            cheque,
            user=request.user,
            bank_treasury_account=bank_account,
            clearing_date=clearing_date,
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "چک وصول شد.")
    return redirect("cheque_detail", pk=cheque.pk)


@login_required
@require_POST
def cheque_bounce(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company_id__in=user_company_ids(request.user))
    bounce_date = _action_date(request, "bounce_date")
    if bounce_date == "INVALID":
        messages.error(request, "تاریخ برگشت معتبر نیست.")
        return redirect("cheque_detail", pk=cheque.pk)
    try:
        services.bounce_cheque(cheque, user=request.user, bounce_date=bounce_date)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "چک برگشتی ثبت شد.")
    return redirect("cheque_detail", pk=cheque.pk)


@login_required
@require_POST
def cheque_return(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company_id__in=user_company_ids(request.user))
    return_date = _action_date(request, "return_date")
    if return_date == "INVALID":
        messages.error(request, "تاریخ عودت معتبر نیست.")
        return redirect("cheque_detail", pk=cheque.pk)
    try:
        services.return_cheque(cheque, user=request.user, return_date=return_date)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "چک به صادرکننده عودت داده شد.")
    return redirect("cheque_detail", pk=cheque.pk)


def _scoped_statement(request, pk):
    return get_object_or_404(
        BankStatement.objects.select_related(
            "company", "treasury_account", "treasury_account__gl_account"
        ),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )


@login_required
def bank_statement_list(request):
    statements = BankStatement.objects.filter(
        company_id__in=user_company_ids(request.user)
    ).select_related("company", "treasury_account")
    if request.GET.get("account"):
        account = get_object_or_404(
            TreasuryAccount,
            pk=request.GET["account"],
            company_id__in=user_company_ids(request.user),
        )
        statements = statements.filter(treasury_account=account)
    accounts = TreasuryAccount.objects.filter(
        company_id__in=user_company_ids(request.user), kind=TreasuryAccount.Kind.BANK
    )
    return render(
        request,
        "treasury/statement_list.html",
        {"statements": statements, "accounts": accounts},
    )


STATEMENT_FILE_STASH_KEY = "statement_file_import"


def _row_noun(file_format):
    """Rejected rows are reported by physical line for CSV and by
    transaction index for the XML formats (Sprint 18)."""
    return "ردیف" if file_format == "csv" else "تراکنش"


def _file_preview_context(parsed, filename):
    return {
        "filename": filename,
        "format": parsed.format,
        "row_count": len(parsed.rows) + len(parsed.rejected),
        "imported_count": len(parsed.rows),
        "rejected": parsed.rejected,
        "row_noun": _row_noun(parsed.format),
        "metadata": parsed.metadata,
    }


def _file_initial(account, parsed):
    """Header initials for the create form: the Sprint 15 chaining
    suggestion first, then the file's own header metadata on top —
    file metadata wins where the file carries it (e.g. OFX has no
    opening balance, so the chaining value stands there). Everything
    stays an editable initial; the user's edits win last."""
    initial = {"treasury_account": account}
    suggestion = reconciliation.suggested_statement_opening(account)
    if suggestion is not None:
        initial["start_date"], initial["opening_balance"] = suggestion
    metadata = parsed.metadata
    if metadata.get("period_start") is not None:
        initial["start_date"] = metadata["period_start"]
    if metadata.get("period_end") is not None:
        initial["end_date"] = metadata["period_end"]
    if metadata.get("opening_balance") is not None:
        initial["opening_balance"] = metadata["opening_balance"]
    if metadata.get("closing_balance") is not None:
        initial["closing_balance"] = metadata["closing_balance"]
    return initial


@login_required
def bank_statement_create(request):
    companies, company = resolve_scoped_company(request)
    initial = {}
    prefill_account = None
    file_preview = None
    file_form = StatementFilePreviewForm(
        company=company,
        companies=companies,
        initial={"company": company} if company is not None else None,
    )
    form = None

    if request.method == "POST" and "statement_file" in request.FILES:
        # Phase 1 of the create-from-file flow: parse the upload,
        # stash the rows, and re-render the create form prefilled
        # with the file's header for review/editing.
        file_form = StatementFilePreviewForm(
            request.POST, request.FILES, company=company, companies=companies
        )
        if company is not None and file_form.is_valid():
            account = file_form.cleaned_data["treasury_account"]
            upload = file_form.cleaned_data["statement_file"]
            try:
                parsed = reconciliation.parse_statement_upload(upload.read())
            except statement_files.UndecodableStatementFile:
                messages.error(request, "فایل باید با کدگذاری UTF-8 باشد.")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                request.session[STATEMENT_FILE_STASH_KEY] = statement_files.parsed_to_stash(
                    parsed,
                    filename=upload.name,
                    account_id=str(account.pk),
                    company_id=str(company.pk),
                )
                initial = _file_initial(account, parsed)
                prefill_account = account
                file_preview = _file_preview_context(parsed, upload.name)
        form = BankStatementForm(company=company, companies=companies, initial=initial)
    elif request.method == "POST":
        form = BankStatementForm(request.POST, company=company, companies=companies)
        if company is not None and form.is_valid():
            data = form.cleaned_data
            stash = request.session.get(STATEMENT_FILE_STASH_KEY)
            use_stash = (
                stash is not None
                and stash.get("company_id") == str(company.pk)
                and stash.get("account_id") == str(data["treasury_account"].pk)
            )
            try:
                if use_stash:
                    parsed = statement_files.parsed_from_stash(stash)
                    statement, report = reconciliation.create_statement_from_upload(
                        company=company,
                        treasury_account=data["treasury_account"],
                        start_date=data["start_date"],
                        end_date=data["end_date"],
                        opening_balance=data["opening_balance"],
                        closing_balance=data["closing_balance"],
                        source_note=data["source_note"],
                        parsed=parsed,
                        user=request.user,
                    )
                else:
                    statement = reconciliation.create_statement(
                        company=company,
                        treasury_account=data["treasury_account"],
                        start_date=data["start_date"],
                        end_date=data["end_date"],
                        opening_balance=data["opening_balance"],
                        closing_balance=data["closing_balance"],
                        source_note=data["source_note"],
                        user=request.user,
                    )
            except ValidationError as exc:
                add_service_errors(form, exc)
                if use_stash:
                    # Keep the file's figures visible next to the
                    # (editable) form so the refusal can be fixed.
                    file_preview = _file_preview_context(
                        statement_files.parsed_from_stash(stash), stash.get("filename", "")
                    )
            else:
                request.session.pop(STATEMENT_FILE_STASH_KEY, None)
                messages.success(request, "صورت‌حساب بانکی ایجاد شد.")
                if use_stash:
                    messages.success(request, f"{report['imported']} ردیف از فایل وارد شد.")
                    for rejected in report["rejected"]:
                        messages.error(
                            request,
                            f"{_row_noun(parsed.format)} {rejected['row']}: {rejected['reason']}",
                        )
                return redirect("bank_statement_detail", pk=statement.pk)
    else:  # GET
        if company is not None and request.GET.get("account"):
            prefill_account = TreasuryAccount.objects.filter(
                pk=request.GET["account"], company=company, kind=TreasuryAccount.Kind.BANK
            ).first()
            if prefill_account is not None:
                initial["treasury_account"] = prefill_account
                suggestion = reconciliation.suggested_statement_opening(prefill_account)
                if suggestion is not None:
                    initial["start_date"], initial["opening_balance"] = suggestion
        stash = request.session.get(STATEMENT_FILE_STASH_KEY) if company is not None else None
        if stash is not None and stash.get("company_id") == str(company.pk):
            account = TreasuryAccount.objects.filter(
                pk=stash.get("account_id"), company=company, kind=TreasuryAccount.Kind.BANK
            ).first()
            if account is not None and (
                prefill_account is None or prefill_account.pk == account.pk
            ):
                parsed = statement_files.parsed_from_stash(stash)
                initial = _file_initial(account, parsed)
                prefill_account = account
                file_preview = _file_preview_context(parsed, stash.get("filename", ""))
        form = BankStatementForm(company=company, companies=companies, initial=initial)
    return render(
        request,
        "treasury/statement_form.html",
        {
            "form": form,
            "file_form": file_form,
            "file_preview": file_preview,
            "companies": companies,
            "company": company,
            "prefill_account": prefill_account,
        },
    )


@login_required
def cheque_book_list(request):
    books = cheque_books.cheque_books_with_counts().filter(
        company_id__in=user_company_ids(request.user)
    )
    if request.GET.get("account"):
        account = get_object_or_404(
            TreasuryAccount,
            pk=request.GET["account"],
            company_id__in=user_company_ids(request.user),
        )
        books = books.filter(treasury_account=account)
    accounts = TreasuryAccount.objects.filter(
        company_id__in=user_company_ids(request.user), kind=TreasuryAccount.Kind.BANK
    )
    return render(
        request,
        "treasury/cheque_book_list.html",
        {"books": books, "accounts": accounts},
    )


@login_required
def cheque_book_create(request):
    companies, company = resolve_scoped_company(request)
    form = ChequeBookForm(request.POST or None, company=company, companies=companies)
    if request.method == "POST" and company is not None and form.is_valid():
        data = form.cleaned_data
        try:
            book = cheque_books.create_cheque_book(
                company=company,
                treasury_account=data["treasury_account"],
                first_number=data["first_number"],
                leaf_count=data["leaf_count"],
                label=data["label"],
                user=request.user,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "دفترچه چک ایجاد شد.")
            return redirect("cheque_book_detail", pk=book.pk)
    return render(
        request,
        "treasury/cheque_book_form.html",
        {"form": form, "companies": companies, "company": company},
    )


@login_required
def cheque_book_detail(request, pk):
    book = get_object_or_404(
        ChequeBook.objects.select_related("company", "treasury_account"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    leaves = book.leaves.select_related("cheque", "cheque__payment", "cheque__payment__party").all()
    unused, used, void = cheque_books.book_counts(book)
    return render(
        request,
        "treasury/cheque_book_detail.html",
        {
            "book": book,
            "leaves": leaves,
            "unused_count": unused,
            "used_count": used,
            "void_count": void,
            "last_leaf": leaves.last() if leaves else None,
        },
    )


@login_required
@require_POST
def cheque_leaf_void(request, leaf_pk):
    leaf = get_object_or_404(ChequeLeaf, pk=leaf_pk, company_id__in=user_company_ids(request.user))
    try:
        cheque_books.void_leaf(leaf, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"برگ {leaf.number} باطل شد.")
    return redirect("cheque_book_detail", pk=leaf.book_id)


def _statement_detail_context(statement, line_form=None, import_form=None):
    summary = reconciliation.reconciliation_summary(statement)
    movements = summary["outstanding_book"]
    return {
        "statement": statement,
        "summary": summary,
        "lines": statement.lines.select_related(
            "matched_journal_line", "matched_journal_line__entry"
        ).all(),
        "line_form": line_form or BankStatementLineForm(),
        "import_form": import_form or StatementImportForm(),
        "match_forms": [
            {
                "row": row,
                "form": StatementMatchForm(
                    statement=statement, initial={"journal_line": row["journal_line"].pk}
                ),
            }
            for row in movements
        ],
    }


@login_required
def bank_statement_detail(request, pk):
    statement = _scoped_statement(request, pk)
    return render(request, "treasury/statement_detail.html", _statement_detail_context(statement))


@login_required
@require_POST
def bank_statement_add_line(request, pk):
    statement = _scoped_statement(request, pk)
    form = BankStatementLineForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            reconciliation.add_statement_line(
                statement,
                line_date=data["line_date"],
                amount=data["amount"],
                description=data["description"],
                reference=data["reference"],
                user=request.user,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "ردیف صورت‌حساب افزوده شد.")
            return redirect("bank_statement_detail", pk=statement.pk)
    return render(
        request,
        "treasury/statement_detail.html",
        _statement_detail_context(statement, line_form=form),
    )


@login_required
@require_POST
def bank_statement_import(request, pk):
    statement = _scoped_statement(request, pk)
    form = StatementImportForm(request.POST, request.FILES)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("bank_statement_detail", pk=statement.pk)
    upload = form.cleaned_data["file"]
    try:
        report = reconciliation.import_statement_file(
            statement, content=upload.read(), user=request.user
        )
    except statement_files.UndecodableStatementFile:
        messages.error(request, "فایل باید با کدگذاری UTF-8 باشد.")
        return redirect("bank_statement_detail", pk=statement.pk)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("bank_statement_detail", pk=statement.pk)
    messages.success(request, f"{report['imported']} ردیف از فایل وارد شد.")
    for rejected in report["rejected"]:
        messages.error(
            request, f"{_row_noun(report['format'])} {rejected['row']}: {rejected['reason']}"
        )
    return redirect("bank_statement_detail", pk=statement.pk)


@login_required
@require_POST
def bank_statement_auto_match(request, pk):
    statement = _scoped_statement(request, pk)
    try:
        result = reconciliation.auto_match(statement, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(
            request,
            f"{result['matched']} ردیف به‌صورت خودکار تطبیق شد؛ {result['remaining']} ردیف باقی ماند.",
        )
    return redirect("bank_statement_detail", pk=statement.pk)


@login_required
@require_POST
def bank_statement_match(request, pk):
    statement = _scoped_statement(request, pk)
    form = StatementMatchForm(request.POST, statement=statement)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("bank_statement_detail", pk=statement.pk)
    journal_line = get_object_or_404(
        JournalLine, pk=form.cleaned_data["journal_line"], entry__company=statement.company
    )
    try:
        reconciliation.match_line(
            form.cleaned_data["statement_line"], journal_line, user=request.user
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "تطبیق ثبت شد.")
    return redirect("bank_statement_detail", pk=statement.pk)


@login_required
@require_POST
def bank_statement_unmatch(request, pk, line_pk):
    statement = _scoped_statement(request, pk)
    line = get_object_or_404(BankStatementLine, pk=line_pk, statement=statement)
    try:
        reconciliation.unmatch_line(line, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "تطبیق لغو شد.")
    return redirect("bank_statement_detail", pk=statement.pk)


@login_required
@require_POST
def bank_statement_complete(request, pk):
    statement = _scoped_statement(request, pk)
    try:
        reconciliation.complete_statement(statement, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "صورت‌حساب نهایی و قفل شد.")
    return redirect("bank_statement_detail", pk=statement.pk)


@login_required
@require_POST
def bank_statement_reopen(request, pk):
    statement = _scoped_statement(request, pk)
    try:
        reconciliation.reopen_statement(statement, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "صورت‌حساب بازگشایی شد.")
    return redirect("bank_statement_detail", pk=statement.pk)


@login_required
def open_items_view(request):
    from apps.organizations.models import Company

    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    items = []
    for company in companies:
        items.extend(reporting.open_items(company))
    return render(request, "treasury/open_items.html", {"items": items})
