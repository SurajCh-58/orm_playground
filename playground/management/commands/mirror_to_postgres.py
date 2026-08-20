"""
management command: mirror_to_postgres

Since 'default' and 'postgres' now both point to the same PostgreSQL
database, this command simply runs the playground migrations against
the default database and seeds the sample data.

Usage
-----
    python manage.py migrate          # creates schema
    python manage.py mirror_to_postgres   # resets seed data (idempotent)
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, OperationalError


class Command(BaseCommand):
    help = (
        "Seed (or re-seed) sample data into the PostgreSQL playground tables. "
        "Idempotent — safe to re-run as a full data reset."
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("ORM Playground — reseed PostgreSQL"))

        self.stdout.write("  Checking PostgreSQL connection …")
        try:
            conn = connections["postgres"]
            conn.ensure_connection()
        except OperationalError as exc:
            raise CommandError(
                f"\nCould not connect to PostgreSQL: {exc}\n\n"
                "Make sure PostgreSQL is running and the env-vars are set:\n"
                "  PG_NAME, PG_USER, PG_PASSWORD, PG_HOST, PG_PORT"
            ) from exc
        self.stdout.write(self.style.SUCCESS("  ✓ Connected"))

        self.stdout.write("  Seeding sample data …")
        _seed(conn)
        self.stdout.write(self.style.SUCCESS("  ✓ Done\n"))
        self.stdout.write(
            self.style.SUCCESS("PostgreSQL is ready. Run queries in the playground!")
        )


def _seed(conn):
    with conn.cursor() as cur:
        # Clear M2M first (FK constraint)
        cur.execute("DELETE FROM playground_book_tags")
        cur.execute("DELETE FROM playground_book")
        cur.execute("DELETE FROM playground_author")
        cur.execute("DELETE FROM playground_tag")

        cur.execute("""
            INSERT INTO playground_author (id, name, country) VALUES
              (1, 'George Orwell',   'UK'),
              (2, 'Chinua Achebe',   'Nigeria'),
              (3, 'Haruki Murakami', 'Japan')
        """)
        cur.execute("""
            INSERT INTO playground_tag (id, name) VALUES
              (1, 'dystopian'),
              (2, 'classic'),
              (3, 'surreal')
        """)
        cur.execute("""
            INSERT INTO playground_book (id, title, price, status, author_id) VALUES
              (1, '1984',               15, 'published', 1),
              (2, 'Animal Farm',        10, 'published', 1),
              (3, 'Things Fall Apart',  18, 'published', 2),
              (4, 'Norwegian Wood',     22, 'draft',     3),
              (5, 'Kafka on the Shore', 20, 'published', 3)
        """)
        cur.execute("""
            INSERT INTO playground_book_tags (book_id, tag_id) VALUES
              (1, 1), (1, 2),
              (2, 2),
              (4, 3),
              (5, 3)
        """)
        for table, col in [
            ("playground_author", "id"),
            ("playground_tag",    "id"),
            ("playground_book",   "id"),
        ]:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), "
                f"(SELECT MAX({col}) FROM {table}))"
            )
