# ORM Playground 🎮

A localhost-only Django project for learning and practising **Django ORM** expressions and **raw PostgreSQL** queries — built entirely with the help of Claude AI as a hands-on learning tool.

> **Fully developed using Claude AI** for learning purposes. Every feature, from the dual-mode query editor to the query profiler and optimization comparison panel, was designed and built through an iterative conversation with Claude.

---

## ⚠️ Security Warning

This project uses `eval()` to run arbitrary Python code. It is designed for **localhost personal practice only**. Never expose this server to a network or deploy it anywhere public.

---

## What Is This For?

ORM Playground gives you a live, interactive environment to:

- **Learn Django ORM** — write Python ORM expressions and instantly see the SQL Django generates behind the scenes
- **Learn PostgreSQL** — run raw SQL queries directly against a real Postgres database
- **Understand query optimization** — measure execution time, count how many database queries your ORM code fires, and compare a slow query against a fast one side by side
- **Spot the N+1 problem** — trigger it deliberately and fix it with `select_related` / `prefetch_related`, then watch the DB query count drop in real time

---

## Setup

```powershell
# Windows — activate your virtual environment first
venv\Scripts\activate
pip install -r requirements.txt
```

Set your PostgreSQL credentials in `.env`:

```env
PG_NAME=ormplayground_db
PG_USER=your_user
PG_PASSWORD=your_password
PG_HOST=localhost
PG_PORT=5432
```

Then run:

```powershell
python manage.py migrate
python manage.py mirror_to_postgres   # seeds sample data
python manage.py runserver
```

Open **http://127.0.0.1:8000/** in your browser.

To reset the sample data at any time:

```powershell
python manage.py mirror_to_postgres
```

---

## Database

This project uses **PostgreSQL only** — no SQLite. Both the `'default'` and `'postgres'` Django database aliases point to the same Postgres database, so ORM queries and raw SQL queries always talk to the same data.

---

## Sample Data

| Model | Rows |
|---|---|
| **Author** | George Orwell (UK), Chinua Achebe (Nigeria), Haruki Murakami (Japan) |
| **Tag** | dystopian, classic, surreal |
| **Book** | 1984, Animal Farm, Things Fall Apart, Norwegian Wood, Kafka on the Shore |

---

## Features

### Landing Page (`/`)

- Displays every table with all its current rows at a glance
- Check any table to pin it as a reference panel on the query page — useful for keeping context while you write queries

### Query Playground (`/query/`)

This is where all the learning happens. The page has two modes toggled from the header:

#### Django ORM Mode

Write Python ORM expressions directly. The playground evaluates them and shows:

- The **result rows** in a table
- The **raw SQL** Django generated — this is how you learn what the ORM actually does
- The full **query profiler** (see below)

#### PostgreSQL Mode

Write raw SQL against the same database. Shows:

- The **result rows** in a table
- The number of **active PostgreSQL backends** at query time
- The full **query profiler** (see below)
- **EXPLAIN ANALYZE** — click Explain to see the full query plan and cost estimates from Postgres
- **Format SQL** — pretty-prints your SQL with correct indentation and uppercase keywords
- **Write confirmation** — INSERT / UPDATE / DELETE / DROP require a confirmation click so you don't accidentally modify data

#### Both Modes

- **Ctrl + Enter** runs the current query
- **Export CSV** — download any result set as a CSV file
- **Query history** — sidebar keeps your last 20 queries per mode; click any entry to reload it
- **Examples sidebar** — pre-written example queries for both modes to get you started
- **Schema inspector** — sidebar shows every playground table with column names and Postgres data types

---

## Query Profiler

Every query run shows a profiler panel with:

| Metric | ORM Mode | SQL Mode |
|---|---|---|
| **Execution time (ms)** | ✅ | ✅ |
| **Execution time (seconds)** | ✅ | ✅ |
| **DB query count** | ✅ | — |
| **Active PG backends** | — | ✅ |
| **Rows returned** | ✅ | ✅ |

In ORM mode, the profiler also has a collapsible **SQL statement log** that lists every individual SQL statement Django issued — with its own execution time — so you can see exactly what happened under the hood (including N+1 queries when they occur).

### Optimization Comparison

Click **📌 Pin as Before** after running any query to save its profiler stats. Then rewrite the query and run it again. A side-by-side comparison panel appears automatically showing Before vs After across every metric:

```
Before:  45.2 ms  |  6 DB queries
After:    3.1 ms  |  1 DB query
▼ Faster by 42.1 ms — 5 fewer DB hits
```

This makes the impact of optimizations like `select_related`, `prefetch_related`, `values()`, and proper indexing immediately visible.

---

## Learning: The N+1 Problem

The classic Django performance trap — and the main reason this profiler was built.

**Trigger N+1 (ORM mode):**

```python
[{"title": b.title, "author": b.author.name} for b in Book.objects.all()]
```

This fires `1 + N` queries: one for all books, then one per unique author. Pin the result.

**Fix it with `select_related`:**

```python
[{"title": b.title, "author": b.author.name} for b in Book.objects.select_related("author").all()]
```

Now it's 1 query — a SQL JOIN. The comparison panel shows the exact reduction.

**ManyToMany version (even more dramatic):**

```python
# N+1 — 1 query per book for tags
[{"title": b.title, "tags": [t.name for t in b.tags.all()]} for b in Book.objects.all()]

# Fixed — 2 queries total, regardless of book count
[{"title": b.title, "tags": [t.name for t in b.tags.all()]} for b in Book.objects.prefetch_related("tags").all()]
```

---

## ORM Names Available

```
Author  Book  Tag  Q  F  Count  Avg  Sum  Max  Min  Value  Coalesce
```

---

## Example ORM Queries

```python
# Basic retrieval
Book.objects.all()
Book.objects.filter(status="published").order_by("-price")
Author.objects.get(name="Haruki Murakami")

# Relationships
Book.objects.filter(tags__name="surreal")
Book.objects.select_related("author").all()           # eliminates N+1

# Annotations and aggregation
Author.objects.annotate(book_count=Count("books"))
Book.objects.aggregate(avg_price=Avg("price"))
Book.objects.aggregate(lo=Min("price"), hi=Max("price"))

# Complex filtering
Book.objects.filter(Q(status="draft") | Q(price__lt=15))

# Projections
Book.objects.values("title", "price", "status")       # returns dicts, not model instances
```

---

## Example SQL Queries

```sql
-- Basic
SELECT * FROM playground_book;
SELECT * FROM playground_book WHERE price > 15 ORDER BY price DESC;

-- Join
SELECT b.title, a.name
FROM playground_book b
JOIN playground_author a ON b.author_id = a.id;

-- Aggregation
SELECT COUNT(*) FROM playground_book WHERE status = 'published';

SELECT a.name, COUNT(b.id) AS book_count
FROM playground_author a
LEFT JOIN playground_book b ON b.author_id = a.id
GROUP BY a.id, a.name;

-- Query plan inspection
EXPLAIN ANALYZE SELECT * FROM playground_book WHERE status = 'published';
```

---

## Project Structure

```
orm_playground/
├── manage.py
├── requirements.txt
├── .env                          ← your Postgres credentials
├── orm_playground/
│   └── settings.py               ← both DB aliases point to same PG DB
└── playground/
    ├── models.py                 ← Author, Tag, Book
    ├── views.py                  ← ORM eval, SQL execution, profiler logic
    ├── sql_guard.py              ← blocks multi-statement and destructive SQL
    ├── management/
    │   └── commands/
    │       └── mirror_to_postgres.py   ← seeds sample data
    ├── migrations/
    └── templates/playground/
        ├── landing.html
        ├── index.html            ← main query playground
        └── _profiler.html        ← profiler panel partial
```

---

## Built With Claude AI

This project was developed entirely through a conversation with **Claude** (Anthropic) as a portfolio and learning exercise. The goal was not just to build a working tool, but to understand every part of it — from Django's query evaluation lifecycle to PostgreSQL's `pg_stat_activity` view to how `connection.queries` works internally.

Every feature was designed, debugged, and refined iteratively. If you're learning Django backend development, building projects like this with an AI pair-programmer is one of the fastest ways to go from theory to real understanding.