"""
views.py — ORM Playground (dual-mode: Django ORM + raw PostgreSQL).

WARNING: This view calls eval() on arbitrary text submitted through a form
that has no authentication. It is only acceptable because this project is
intended for localhost personal practice. Never expose this server beyond
localhost.  See README.md for details.

New features added:
  - Postgres-only: 'default' and 'postgres' aliases both point to the same PG DB
  - Query history (last 20) per mode, stored in session
  - Execution time displayed for every query (ms AND seconds)
  - DB query count: how many SQL statements Django issued (ORM mode)
  - EXPLAIN ANALYZE support (SQL mode — "Explain" button)
  - CSV export of last result set
  - Schema inspector: column names + types for every playground table
  - SQL formatter: "Format SQL" button pretty-prints the query
  - [NEW] Query Profiler: pin a "before" result and compare with "after"
  - [NEW] DB process info via pg_stat_activity (PostgreSQL mode)
"""

from __future__ import annotations

import csv
import io
import re
import time
import traceback
from typing import Any

import sqlparse
from django.conf import settings
from django.db import OperationalError, connection, connections, reset_queries
from django.db.models import Avg, Count, F, Max, Min, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import redirect, render

from . import models as _models
from .models import Author, Book, Tag  # explicit imports keep ORM eval names working
from .sql_guard import is_single_statement, is_write_query

# ── Constants ────────────────────────────────────────────────────────────────

SESSION_QUERY    = "pg_last_query"
SESSION_RESULT   = "pg_last_result"
SESSION_MODE     = "pg_mode"              # "orm" | "pgsql"
SESSION_SELECTED = "pg_selected_tables"   # list[str]
SESSION_HISTORY_ORM  = "pg_history_orm"   # list of {query, label}
SESSION_HISTORY_SQL  = "pg_history_sql"   # list of {query, label}
SESSION_PINNED   = "pg_pinned_result"     # pinned "before" result for comparison

HISTORY_MAX = 20

from django.apps import apps as _django_apps

# Auto-discover every concrete model in the playground app.
ALL_TABLES: dict[str, type] = {
    model.__name__: model
    for model in _django_apps.get_app_config("playground").get_models()
    if not model._meta.abstract and not model._meta.auto_created
}

ORM_NAMES: dict[str, Any] = {
    **ALL_TABLES,
    "Q":       Q,
    "F":       F,
    "Count":   Count,
    "Avg":     Avg,
    "Sum":     Sum,
    "Max":     Max,
    "Min":     Min,
    "Value":   Value,
    "Coalesce": Coalesce,
}

MODEL_FIELD_ORDER: dict[type, list[str]] = {
    Author: ["id", "name", "country"],
    Tag:    ["id", "name"],
    Book:   ["id", "title", "price", "status", "author_id"],
}

EMPTY_OUTCOME: dict[str, Any] = {
    "result_kind":   None,
    "columns":       None,
    "rows":          None,
    "sql":           None,
    "scalar_result": None,
    "error":         None,
    "exec_ms":       None,
    # ── NEW profiling fields ──
    "exec_sec":      None,   # execution time in seconds (rounded to 4 dp)
    "db_query_count": None,  # number of SQL statements issued (ORM mode)
    "db_queries":    None,   # list of individual SQL statements with their times
    "pg_processes":  None,   # active PG backend count (SQL mode)
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _friendly_error(raw_tb: str) -> dict:
    lines = raw_tb.strip().splitlines()
    exc_line = exc_type = exc_msg = ""
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith("^") and not line.startswith("~") and (
            "Error" in line or "Exception" in line or "ValueError" in line
        ):
            exc_line = line
            if ":" in line:
                exc_type, _, exc_msg = line.partition(":")
                exc_type = exc_type.strip().split(".")[-1]
                exc_msg  = exc_msg.strip()
            break
    if not exc_line:
        for line in reversed(lines):
            if line.strip():
                exc_line = line.strip()
                break

    FRIENDLY_TYPES = {
        "ProgrammingError":  "SQL Error",
        "OperationalError":  "Database Error",
        "IntegrityError":    "Integrity Error",
        "NameError":         "Name Error",
        "AttributeError":    "Attribute Error",
        "SyntaxError":       "Syntax Error",
        "TypeError":         "Type Error",
        "ValueError":        "Value Error",
        "IndentationError":  "Indentation Error",
        "KeyError":          "Key Error",
        "IndexError":        "Index Error",
        "ZeroDivisionError": "Division by Zero",
    }
    title = FRIENDLY_TYPES.get(exc_type, exc_type or "Error")

    line_hint = ""
    for ln in lines:
        if ln.strip().startswith("LINE "):
            line_hint = ln.strip()
            break

    hint = ""
    msg_lower = exc_msg.lower()
    if "does not exist" in msg_lower and "relation" in msg_lower:
        m = re.search(r'relation "([^"]+)"', exc_msg)
        bad_table = m.group(1) if m else ""
        hint = (
            f'Table "{bad_table}" not found. '
            "Check the spelling — Django table names follow the pattern "
            "<appname>_<modelname> (e.g. playground_author, playground_book)."
        )
    elif "column" in msg_lower and "does not exist" in msg_lower:
        m = re.search(r'column "([^"]+)"', exc_msg)
        bad_col = m.group(1) if m else ""
        hint = f'Column "{bad_col}" not found. Check the field name in your query.'
    elif "syntax error" in msg_lower:
        hint = "PostgreSQL syntax error. Check for missing commas, unmatched parentheses, or wrong keywords."
    elif "is not defined" in msg_lower:
        m = re.search(r"'([^']+)' is not defined", exc_msg)
        name = m.group(1) if m else ""
        model_names = ", ".join(sorted(ALL_TABLES.keys()))
        hint = (
            f'"{name}" is not available in ORM mode. '
            f"Available models: {model_names}. "
            "Also available: Q, F, Count, Avg, Sum, Max, Min, Value, Coalesce."
        )
    elif "could not connect" in msg_lower or "connection refused" in msg_lower:
        hint = "PostgreSQL is not reachable. Make sure the server is running and your .env vars (PG_HOST, PG_PORT, PG_NAME, PG_USER, PG_PASSWORD) are correct."
    elif "multiple statements" in msg_lower:
        hint = "Only one SQL statement is allowed per run. Split your queries and run them separately."
    elif "'queryset' object is not subscriptable" in msg_lower or "queryset" in msg_lower:
        hint = "You're treating a QuerySet like a list. Did you mean .first() or list(...) ?"
    elif "object has no attribute" in msg_lower:
        m = re.search(r"'([^']+)' object has no attribute '([^']+)'", exc_msg)
        if m:
            hint = f"{m.group(1)} has no attribute '{m.group(2)}'. Check the field/method name."

    return {
        "title":     title,
        "detail":    exc_msg or exc_line,
        "line_hint": line_hint,
        "hint":      hint,
        "raw":       raw_tb,
    }


def _columns_for(obj) -> list[str]:
    known = MODEL_FIELD_ORDER.get(type(obj))
    if known:
        return known
    return [f.name for f in type(obj)._meta.concrete_fields]


def _row(obj, columns: list[str]) -> list:
    return [getattr(obj, col, "") for col in columns]


def _build_table(items: list) -> tuple[list | None, list | None]:
    if not items:
        return None, None
    first = items[0]
    if isinstance(first, dict):
        cols = list(first.keys())
        rows = [[item.get(c, "") for c in cols] for item in items]
        return cols, rows
    if hasattr(first, "_meta"):
        cols = _columns_for(first)
        rows = [_row(obj, cols) for obj in items]
        return cols, rows
    return ["value"], [[item] for item in items]


def _serialise(outcome: dict) -> dict:
    rows = outcome["rows"]
    return {
        **outcome,
        "rows": [[str(c) for c in row] for row in rows] if rows else rows,
    }


def _clean_selection(raw: list[str] | None) -> list[str]:
    raw_set = set(raw or [])
    return [label for label in ALL_TABLES if label in raw_set]


def _push_history(session, mode: str, query: str) -> None:
    key = SESSION_HISTORY_ORM if mode == "orm" else SESSION_HISTORY_SQL
    history: list[dict] = session.get(key, [])
    history = [h for h in history if h["query"] != query]
    label = (query[:60] + "…") if len(query) > 60 else query
    history.insert(0, {"query": query, "label": label})
    session[key] = history[:HISTORY_MAX]


def _get_history(session, mode: str) -> list[dict]:
    key = SESSION_HISTORY_ORM if mode == "orm" else SESSION_HISTORY_SQL
    return session.get(key, [])


# ── NEW: Fetch active PostgreSQL backend count ────────────────────────────────

def _pg_active_processes() -> int | None:
    """
    Return the number of active backend connections currently visible in
    pg_stat_activity (excluding idle and this query itself).
    Returns None if the query fails (e.g. permission denied).
    """
    try:
        with connections["postgres"].cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM pg_stat_activity
                WHERE state != 'idle'
                  AND pid != pg_backend_pid()
            """)
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception:
        return None


# ── Schema introspection ─────────────────────────────────────────────────────

def _schema_data(labels: list[str] | None = None) -> list[dict]:
    wanted = labels if labels is not None else list(ALL_TABLES.keys())
    result = []
    for label in wanted:
        model = ALL_TABLES[label]
        cols = MODEL_FIELD_ORDER.get(model, [f.name for f in model._meta.concrete_fields])
        try:
            qs   = model.objects.using("default").all()
            objs = list(qs)
            rows = [_row(obj, cols) for obj in objs]
        except Exception:
            objs = []
            rows = []
        result.append({
            "label":    label,
            "model":    model,
            "db_table": model._meta.db_table,
            "columns":  cols,
            "rows":     rows,
            "count":    len(objs),
        })
    return result


def _pg_schema_info() -> list[dict]:
    playground_tables = [m._meta.db_table for m in ALL_TABLES.values()]
    for model in ALL_TABLES.values():
        for field in model._meta.many_to_many:
            through = field.remote_field.through
            if through._meta.auto_created:
                playground_tables.append(through._meta.db_table)

    results = []
    try:
        with connections["postgres"].cursor() as cursor:
            cursor.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = ANY(%s)
                ORDER BY table_name, ordinal_position
            """, [playground_tables])
            rows = cursor.fetchall()

        from collections import defaultdict
        by_table: dict[str, list] = defaultdict(list)
        for table_name, col_name, data_type in rows:
            by_table[table_name].append({"name": col_name, "type": data_type})

        for tname in sorted(by_table.keys()):
            results.append({"table": tname, "columns": by_table[tname]})
    except Exception:
        pass
    return results


# ── ORM execution ────────────────────────────────────────────────────────────

_SQL_STARTERS = frozenset({
    "select", "insert", "update", "delete", "create", "drop",
    "alter", "explain", "pragma", "with", "begin", "commit",
    "rollback", "truncate", "grant", "revoke", "show",
})


def _looks_like_sql(query: str) -> bool:
    tokens = query.strip().split()
    return bool(tokens) and tokens[0].lower() in _SQL_STARTERS


def _run_orm(raw_query: str) -> dict:
    if not raw_query.strip():
        return dict(EMPTY_OUTCOME)

    if _looks_like_sql(raw_query):
        return {
            **dict(EMPTY_OUTCOME),
            "error": {
                "title":     "Wrong Mode",
                "detail":    "This looks like a SQL query, not a Django ORM expression.",
                "line_hint": "",
                "hint":      (
                    "Switch to PostgreSQL mode (toggle at the top of the page) to run raw SQL. "
                    "ORM mode expects a Python expression such as "
                    "Book.objects.all() or Author.objects.filter(country='Japan')."
                ),
                "raw": "",
            },
        }

    result_kind = columns = rows = sql = scalar_result = error = None
    exec_ms = exec_sec = db_query_count = db_queries = None

    try:
        # ── Enable Django query logging ──────────────────────────────────────
        # Django only logs queries when DEBUG=True (settings.DEBUG).
        # We temporarily force it on so we can capture the count & SQL text.
        original_debug = settings.DEBUG
        settings.DEBUG = True
        reset_queries()   # clear any leftover queries from earlier in this request

        t0 = time.monotonic()
        value = eval(raw_query, {"__builtins__": {}}, dict(ORM_NAMES))  # noqa: S307

        if isinstance(value, QuerySet):
            sql   = str(value.query)
            items = list(value)          # ← this is when the DB hit happens
            elapsed = time.monotonic() - t0

            # Capture query log BEFORE resetting DEBUG
            logged = connection.queries[:]
            settings.DEBUG = original_debug

            exec_ms        = round(elapsed * 1000, 1)
            exec_sec       = round(elapsed, 4)
            db_query_count = len(logged)
            db_queries     = [
                {"sql": q["sql"], "time_ms": round(float(q["time"]) * 1000, 2)}
                for q in logged
            ]
            columns, rows  = _build_table(items)
            result_kind    = "queryset" if columns is not None else "empty_queryset"

        elif hasattr(value, "_meta") and hasattr(value, "pk"):
            elapsed = time.monotonic() - t0
            logged  = connection.queries[:]
            settings.DEBUG = original_debug

            exec_ms        = round(elapsed * 1000, 1)
            exec_sec       = round(elapsed, 4)
            db_query_count = len(logged)
            db_queries     = [
                {"sql": q["sql"], "time_ms": round(float(q["time"]) * 1000, 2)}
                for q in logged
            ]
            result_kind = "instance"
            columns     = _columns_for(value)
            rows        = [_row(value, columns)]

        else:
            elapsed = time.monotonic() - t0
            logged  = connection.queries[:]
            settings.DEBUG = original_debug

            exec_ms        = round(elapsed * 1000, 1)
            exec_sec       = round(elapsed, 4)
            db_query_count = len(logged)
            db_queries     = [
                {"sql": q["sql"], "time_ms": round(float(q["time"]) * 1000, 2)}
                for q in logged
            ]
            result_kind  = "scalar"
            scalar_result = repr(value)

    except Exception:
        settings.DEBUG = original_debug
        error = _friendly_error(traceback.format_exc())

    return {
        "result_kind":    result_kind,
        "columns":        columns,
        "rows":           rows,
        "sql":            sql,
        "scalar_result":  scalar_result,
        "error":          error,
        "exec_ms":        exec_ms,
        "exec_sec":       exec_sec,
        "db_query_count": db_query_count,
        "db_queries":     db_queries,
        "pg_processes":   None,
    }


# ── PostgreSQL execution ──────────────────────────────────────────────────────

def _run_pgsql(raw_query: str, confirmed_write: bool = False) -> dict:
    if not raw_query.strip():
        return dict(EMPTY_OUTCOME)

    result_kind = columns = rows = sql = scalar_result = error = None
    exec_ms = exec_sec = pg_processes = None

    if is_write_query(raw_query) and not confirmed_write:
        return {**dict(EMPTY_OUTCOME), "needs_write_confirm": True}

    try:
        if not is_single_statement(raw_query):
            raise ValueError(
                "Multiple statements are not allowed in the sandbox. "
                "Submit one statement at a time."
            )

        # Grab active process count BEFORE running the query
        pg_processes = _pg_active_processes()

        with connections["postgres"].cursor() as cursor:
            t0 = time.monotonic()
            cursor.execute(raw_query)
            elapsed = time.monotonic() - t0
            exec_ms = round(elapsed * 1000, 1)
            exec_sec = round(elapsed, 4)

            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                fetched = cursor.fetchall()
                rows    = [list(r) for r in fetched]
                result_kind = "queryset" if rows else "empty_queryset"
            else:
                result_kind  = "scalar"
                scalar_result = f"{cursor.rowcount} row(s) affected"

        sql = raw_query

    except OperationalError:
        error = _friendly_error(traceback.format_exc())
        error["hint"] = (
            "PostgreSQL is not reachable. Make sure the server is running and your "
            ".env vars are correct: PG_HOST, PG_PORT, PG_NAME, PG_USER, PG_PASSWORD."
        )
    except Exception:
        error = _friendly_error(traceback.format_exc())

    return {
        "result_kind":        result_kind,
        "columns":            columns,
        "rows":               rows,
        "sql":                sql,
        "scalar_result":      scalar_result,
        "error":              error,
        "exec_ms":            exec_ms,
        "exec_sec":           exec_sec,
        "db_query_count":     None,
        "db_queries":         None,
        "pg_processes":       pg_processes,
        "needs_write_confirm": False,
    }


def _run_explain(raw_query: str) -> dict:
    """Run EXPLAIN ANALYZE on *raw_query* and return the plan as a scalar result."""
    if not raw_query.strip():
        return dict(EMPTY_OUTCOME)

    error = scalar_result = exec_ms = exec_sec = None
    result_kind = "scalar"

    try:
        if not is_single_statement(raw_query):
            raise ValueError("EXPLAIN only works on a single statement.")

        with connections["postgres"].cursor() as cursor:
            t0 = time.monotonic()
            cursor.execute("EXPLAIN ANALYZE " + raw_query)
            elapsed = time.monotonic() - t0
            exec_ms  = round(elapsed * 1000, 1)
            exec_sec = round(elapsed, 4)
            plan_rows = cursor.fetchall()
            scalar_result = "\n".join(r[0] for r in plan_rows)

    except Exception:
        error = _friendly_error(traceback.format_exc())
        result_kind = None

    return {
        "result_kind":    result_kind,
        "columns":        None,
        "rows":           None,
        "sql":            "EXPLAIN ANALYZE " + raw_query,
        "scalar_result":  scalar_result,
        "error":          error,
        "exec_ms":        exec_ms,
        "exec_sec":       exec_sec,
        "db_query_count": None,
        "db_queries":     None,
        "pg_processes":   None,
    }


def _format_sql(raw_query: str) -> str:
    try:
        return sqlparse.format(
            raw_query,
            reindent=True,
            keyword_case="upper",
            identifier_case="lower",
            strip_comments=False,
            indent_width=4,
        )
    except Exception:
        return raw_query


# ── Views ────────────────────────────────────────────────────────────────────

def landing(request):
    if request.method == "POST":
        selected = _clean_selection(request.POST.getlist("tables"))
        request.session[SESSION_SELECTED] = selected
        return redirect("playground:index")

    tables = _schema_data()
    selected = _clean_selection(request.session.get(SESSION_SELECTED))
    context = {
        "tables":        tables,
        "selected_keys": selected,
    }
    return render(request, "playground/landing.html", context)


def index(request):
    mode = request.session.get(SESSION_MODE, "orm")
    needs_write_confirm = False
    formatted_query = None

    if request.method == "POST":

        # ── Mode switch ───────────────────────────────────────────────────
        if "set_mode" in request.POST:
            mode = request.POST["set_mode"]
            if mode not in ("orm", "pgsql"):
                mode = "orm"
            request.session[SESSION_MODE] = mode
            query_text = request.session.get(SESSION_QUERY, "")
            outcome    = request.session.get(SESSION_RESULT) or dict(EMPTY_OUTCOME)

        # ── Format SQL ────────────────────────────────────────────────────
        elif "format_sql" in request.POST:
            query_text = request.POST.get("query", "").strip()
            formatted_query = _format_sql(query_text)
            request.session[SESSION_QUERY] = formatted_query
            query_text = formatted_query
            outcome = request.session.get(SESSION_RESULT) or dict(EMPTY_OUTCOME)

        # ── CSV export ────────────────────────────────────────────────────
        elif "export_csv" in request.POST:
            cached = request.session.get(SESSION_RESULT) or {}
            cols = cached.get("columns") or []
            rows = cached.get("rows") or []
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(cols)
            writer.writerows(rows)
            response = HttpResponse(buf.getvalue(), content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="query_results.csv"'
            return response

        # ── Pin current result as "before" (for comparison) ──────────────
        elif "pin_result" in request.POST:
            current = request.session.get(SESSION_RESULT) or {}
            pinned = {
                "query":          request.session.get(SESSION_QUERY, ""),
                "exec_ms":        current.get("exec_ms"),
                "exec_sec":       current.get("exec_sec"),
                "db_query_count": current.get("db_query_count"),
                "pg_processes":   current.get("pg_processes"),
                "row_count":      len(current.get("rows") or []),
            }
            request.session[SESSION_PINNED] = pinned
            query_text = request.session.get(SESSION_QUERY, "")
            outcome    = current or dict(EMPTY_OUTCOME)

        # ── Clear pinned result ───────────────────────────────────────────
        elif "clear_pin" in request.POST:
            request.session.pop(SESSION_PINNED, None)
            query_text = request.session.get(SESSION_QUERY, "")
            outcome    = request.session.get(SESSION_RESULT) or dict(EMPTY_OUTCOME)

        # ── Run query ─────────────────────────────────────────────────────
        else:
            query_text      = request.POST.get("query", "").strip()
            confirmed_write = request.POST.get("confirm_write") == "1"
            is_explain      = "run_explain" in request.POST

            if is_explain:
                outcome = _run_explain(query_text)
            elif mode == "pgsql":
                outcome = _run_pgsql(query_text, confirmed_write)
                needs_write_confirm = outcome.pop("needs_write_confirm", False)
            else:
                outcome = _run_orm(query_text)

            if not needs_write_confirm and query_text:
                _push_history(request.session, mode, query_text)

            request.session[SESSION_QUERY]  = query_text
            request.session[SESSION_RESULT] = _serialise(outcome)

    else:
        query_text = request.session.get(SESSION_QUERY, "")
        outcome    = request.session.get(SESSION_RESULT) or dict(EMPTY_OUTCOME)

    selected = _clean_selection(request.session.get(SESSION_SELECTED))
    reference_tables = _schema_data(selected) if selected else []
    history    = _get_history(request.session, mode)
    schema_info = _pg_schema_info()
    pinned      = request.session.get(SESSION_PINNED)

    context = {
        "mode":                mode,
        "query_text":          query_text,
        "needs_write_confirm": needs_write_confirm,
        "selected_keys":       selected,
        "reference_tables":    reference_tables,
        "history":             history,
        "schema_info":         schema_info,
        "pinned":              pinned,
        **outcome,
    }
    return render(request, "playground/index.html", context)
