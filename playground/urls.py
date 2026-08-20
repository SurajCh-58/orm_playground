from django.urls import path

from . import views

app_name = "playground"

urlpatterns = [
    path("",       views.landing, name="landing"),
    path("query/", views.index,   name="index"),
]
