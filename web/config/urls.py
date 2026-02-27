# -*- coding: utf-8 -*-
from django.urls import path
from search.views import index, document

urlpatterns = [
    path("", index, name="index"),
    path("documents/<path:filename>", document, name="document"),
]
