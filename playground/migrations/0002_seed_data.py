from django.db import migrations


def seed_data(apps, schema_editor):
    Author = apps.get_model("playground", "Author")
    Tag = apps.get_model("playground", "Tag")
    Book = apps.get_model("playground", "Book")

    # --- Authors ---
    orwell = Author.objects.create(name="George Orwell", country="UK")
    achebe = Author.objects.create(name="Chinua Achebe", country="Nigeria")
    murakami = Author.objects.create(name="Haruki Murakami", country="Japan")

    # --- Tags ---
    dystopian = Tag.objects.create(name="dystopian")
    classic = Tag.objects.create(name="classic")
    surreal = Tag.objects.create(name="surreal")

    # --- Books ---
    nineteen_eighty_four = Book.objects.create(
        title="1984", price=15, status="published", author=orwell
    )
    animal_farm = Book.objects.create(
        title="Animal Farm", price=10, status="published", author=orwell
    )
    Book.objects.create(
        title="Things Fall Apart", price=18, status="published", author=achebe
    )
    norwegian_wood = Book.objects.create(
        title="Norwegian Wood", price=22, status="draft", author=murakami
    )
    kafka_on_the_shore = Book.objects.create(
        title="Kafka on the Shore", price=20, status="published", author=murakami
    )

    # --- Tag assignments (M2M) ---
    nineteen_eighty_four.tags.set([dystopian, classic])
    animal_farm.tags.set([classic])
    norwegian_wood.tags.set([surreal])
    kafka_on_the_shore.tags.set([surreal])
    # Things Fall Apart is left untagged; not specified in the seed data spec.


def unseed_data(apps, schema_editor):
    Author = apps.get_model("playground", "Author")
    Tag = apps.get_model("playground", "Tag")
    Book = apps.get_model("playground", "Book")

    # Deleting these three authors/tags cascades to their books and clears
    # the M2M through-table rows, fully reversing seed_data().
    Book.objects.filter(
        title__in=[
            "1984",
            "Animal Farm",
            "Things Fall Apart",
            "Norwegian Wood",
            "Kafka on the Shore",
        ]
    ).delete()
    Author.objects.filter(
        name__in=["George Orwell", "Chinua Achebe", "Haruki Murakami"]
    ).delete()
    Tag.objects.filter(name__in=["dystopian", "classic", "surreal"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("playground", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_data, unseed_data),
    ]
