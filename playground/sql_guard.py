"""
sql_guard.py — Table-extraction and write-detection for the raw-SQL gate.

All public functions are pure (no Django or DB imports needed) so they can
be unit-tested in isolation before being wired into any view.
"""

from __future__ import annotations

import sqlparse
import sqlparse.tokens as T
from sqlparse.sql import Function, Identifier, IdentifierList, Parenthesis, Where, Comparison


# DML write verbs
_WRITE_VERBS: frozenset[str] = frozenset({"INSERT", "UPDATE", "DELETE", "REPLACE"})
_DDL_VERBS: frozenset[str] = frozenset({"DROP", "CREATE", "ALTER", "TRUNCATE"})
# Keywords that introduce a table reference
_TABLE_TRIGGERS: frozenset[str] = frozenset({
    "FROM", "JOIN",
    "INTO",        # INSERT INTO
    "UPDATE",      # UPDATE tablename SET ...
    "TABLE",       # DROP/CREATE TABLE tablename
})


def _real_statements(sql: str) -> list:
    """Return only non-whitespace-only parsed statements."""
    results = []
    for s in sqlparse.parse(sql):
        flat = list(s.flatten())
        if any(t.ttype not in (T.Whitespace, T.Newline, T.Comment.Single,
                               T.Comment.Multiline, None)
               for t in flat):
            results.append(s)
    return results


def _token_upper(token) -> str:
    return token.normalized.upper().strip()


def _get_table_name(identifier: Identifier) -> str | None:
    """
    Extract the real table name from an Identifier, ignoring aliases.
    For 'book b' or 'book AS b', returns 'book'.
    For dotted 'schema.table', returns 'table'.
    """
    real = identifier.get_real_name()
    return real.lower() if real else None


def _walk(token_list, tables: set[str], in_select_list: bool = False) -> None:
    """
    Recursively walk a token list and collect table names into *tables*.
    *in_select_list* is True when we are inside the SELECT column list,
    so we do NOT treat identifiers there as table names.
    """
    collect_next = False   # should the next identifier be a table name?
    ddl_context = False    # we just saw a DDL verb (DROP/CREATE/ALTER/TRUNCATE)

    tokens = token_list.tokens
    i = 0
    while i < len(tokens):
        token = tokens[i]
        ttype = token.ttype

        # --- skip whitespace/comments ---
        if ttype in (T.Whitespace, T.Newline,
                     T.Comment.Single, T.Comment.Multiline):
            i += 1
            continue

        # --- recurse into subgroups ---
        if isinstance(token, Parenthesis):
            _walk(token, tables)
            collect_next = False
            ddl_context = False
            i += 1
            continue

        if isinstance(token, Where):
            _walk(token, tables)
            collect_next = False
            ddl_context = False
            i += 1
            continue

        if isinstance(token, Comparison):
            # Nothing to collect here for table names
            i += 1
            continue

        # --- IdentifierList: only collect if we are expecting table names ---
        if isinstance(token, IdentifierList):
            if collect_next:
                for item in token.get_identifiers():
                    if isinstance(item, Identifier):
                        name = _get_table_name(item)
                        if name:
                            tables.add(name)
            # Either way, recurse to catch subqueries
            for item in token.get_identifiers():
                if hasattr(item, 'tokens'):
                    _walk(item, tables, in_select_list=not collect_next)
            collect_next = False
            ddl_context = False
            i += 1
            continue

        # --- Single Identifier ---
        if isinstance(token, Identifier):
            if collect_next:
                name = _get_table_name(token)
                if name:
                    tables.add(name)
                collect_next = False
                ddl_context = False
                # Still recurse into the identifier for subqueries
                _walk(token, tables)
            else:
                # Not collecting a table name; recurse for subqueries/nested
                _walk(token, tables, in_select_list=in_select_list)
            i += 1
            continue

        # --- Function token (INSERT INTO tablename(col,...) ) ---
        if isinstance(token, Function):
            if collect_next:
                real = token.get_real_name()
                if real:
                    tables.add(real.lower())
                collect_next = False
            i += 1
            continue

        # --- DML keyword ---
        if ttype is T.Keyword.DML:
            val = _token_upper(token)
            if val == "UPDATE":
                collect_next = True
            elif val == "SELECT":
                collect_next = False  # next identifiers are columns, not tables
            else:
                collect_next = False
            ddl_context = False
            i += 1
            continue

        # --- DDL keyword ---
        if ttype is T.Keyword.DDL:
            ddl_context = True
            collect_next = False
            i += 1
            continue

        # --- Regular Keyword ---
        if ttype is T.Keyword:
            val = _token_upper(token)
            if val in ("FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN",
                       "FULL JOIN", "CROSS JOIN", "LEFT OUTER JOIN",
                       "RIGHT OUTER JOIN", "STRAIGHT_JOIN"):
                collect_next = True
                ddl_context = False
            elif val == "INTO":
                collect_next = True
                ddl_context = False
            elif val == "TABLE" and ddl_context:
                collect_next = True
                ddl_context = False
            elif val in ("SET", "WHERE", "ON", "GROUP", "ORDER", "HAVING",
                         "LIMIT", "OFFSET", "UNION", "EXCEPT", "INTERSECT",
                         "SELECT", "RETURNING"):
                collect_next = False
            # else: unknown keyword, leave collect_next as-is
            i += 1
            continue

        # --- Bare Name token directly after a trigger ---
        if ttype is T.Name and collect_next:
            tables.add(token.normalized.lower())
            collect_next = False
            ddl_context = False
            i += 1
            continue

        # Everything else: punctuation, literals, operators …
        # Only reset collect_next for punctuation/operators that clearly end a
        # table-name position.
        if ttype in (T.Punctuation, T.Operator, T.Operator.Comparison,
                     T.Literal.String.Single, T.Literal.Number.Integer,
                     T.Literal.Number.Float):
            collect_next = False
        i += 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_single_statement(sql: str) -> bool:
    """Return True if *sql* contains exactly one SQL statement."""
    return len(_real_statements(sql)) == 1


def extract_tables(sql: str) -> set[str]:
    """
    Return the set of table names (lowercase) referenced in *sql*.
    Input must be a single statement.
    """
    parsed = sqlparse.parse(sql)
    if not parsed:
        return set()
    tables: set[str] = set()
    _walk(parsed[0], tables)
    return tables


def is_write_query(sql: str) -> bool:
    """Return True if *sql* is a DML write or DDL statement."""
    parsed = sqlparse.parse(sql)
    if not parsed:
        return False
    for token in parsed[0].flatten():
        if token.ttype in (T.Keyword.DML, T.Keyword.DDL):
            return token.normalized.upper().strip() in (_WRITE_VERBS | _DDL_VERBS)
    return False


def validate_for_lock(sql: str, locked_table: str) -> str | None:
    """
    Validate *sql* against a table lock.
    Returns None on success, or a human-readable error string.
    """
    if not is_single_statement(sql):
        return (
            "Multiple statements are not allowed in the practice sandbox. "
            "Run one statement at a time."
        )
    tables = extract_tables(sql)
    locked = locked_table.lower()
    bad = {t for t in tables if t != locked}
    if bad:
        return (
            f"Query references table(s) outside the locked scope "
            f"({', '.join(sorted(bad))}). "
            f"Only '{locked_table}' is allowed while this table is selected."
        )
    return None


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cases = [
        ("SELECT * FROM book", {"book"}, False, "basic SELECT"),
        ("SELECT * FROM book WHERE id=1", {"book"}, False, "SELECT with WHERE"),
        ("SELECT b.title, a.name FROM book b JOIN author a ON b.author_id=a.id",
         {"book", "author"}, False, "aliased JOIN"),
        ("SELECT * FROM book WHERE author_id IN (SELECT id FROM author WHERE country='Japan')",
         {"book", "author"}, False, "subquery in WHERE"),
        ("INSERT INTO book (title, price) VALUES ('Test', 10)",
         {"book"}, True, "INSERT INTO with cols"),
        ("INSERT INTO book VALUES (1, 'x', 10, 'published', 1)",
         {"book"}, True, "INSERT INTO bare"),
        ("UPDATE book SET price=99 WHERE id=1", {"book"}, True, "UPDATE"),
        ("DELETE FROM book WHERE id=1", {"book"}, True, "DELETE FROM"),
        ("DROP TABLE book", {"book"}, True, "DROP TABLE"),
        ("SELECT * FROM book; DROP TABLE book",
         None, None, "multi-statement rejected"),
        ("SELECT * FROM book WHERE title = 'hello; DROP TABLE book'",
         {"book"}, False, "semicolon in string literal safe"),
        ("SELECT * FROM tag INNER JOIN book ON tag.id = book.author_id",
         {"tag", "book"}, False, "INNER JOIN"),
        ("SELECT COUNT(*) FROM book GROUP BY status",
         {"book"}, False, "aggregate"),
        ("SELECT * FROM book LEFT JOIN author ON book.author_id = author.id",
         {"book", "author"}, False, "LEFT JOIN"),
        ("WITH cte AS (SELECT id FROM author) SELECT * FROM book JOIN cte ON book.author_id=cte.id",
         {"book", "author", "cte"}, False, "CTE - tables detected"),
    ]

    passed = 0
    for sql, exp_tables, exp_write, desc in cases:
        if exp_tables is None:
            ok = not is_single_statement(sql)
            status = "PASS" if ok else "FAIL"
        else:
            got_tables = extract_tables(sql)
            got_write = is_write_query(sql)
            ok = got_tables == exp_tables and got_write == exp_write
            status = "PASS" if ok else "FAIL"
            if not ok:
                print(f"{status}: {desc}")
                print(f"       tables: got {got_tables}  expected {exp_tables}")
                print(f"       write:  got {got_write}  expected {exp_write}")
                passed += int(ok)
                continue
        print(f"{status}: {desc}")
        passed += int(ok)

    print(f"\n{passed}/{len(cases)} passed")
