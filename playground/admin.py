from django.contrib import admin

from .models import Author, Book, Tag


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "country")
    search_fields = ("name", "country")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "price", "status", "author")
    list_filter = ("status", "author")
    search_fields = ("title",)
    filter_horizontal = ("tags",)
