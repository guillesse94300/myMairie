# -*- coding: utf-8 -*-
from pathlib import Path
from django.shortcuts import render
from django.http import HttpRequest, HttpResponse, FileResponse, Http404
from django.conf import settings

from . import vector_search

DOCUMENTS_ROOT = getattr(settings, "MAIRIE_ROOT", Path(__file__).resolve().parent.parent.parent)


def document(request: HttpRequest, filename: str) -> HttpResponse:
    """Sert un document PDF par son nom de fichier (sécurisé : pas de path traversal)."""
    if ".." in filename or "/" in filename.replace("\\", "/"):
        raise Http404("Chemin non autorisé")
    path = Path(DOCUMENTS_ROOT) / filename
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise Http404("Document introuvable")
    return FileResponse(
        open(path, "rb"),
        as_attachment=False,
        content_type="application/pdf",
        filename=path.name,
    )


def index(request: HttpRequest) -> HttpResponse:
    query = (request.GET.get("q") or request.POST.get("q") or "").strip()
    results = []
    error = None
    if query:
        try:
            results = vector_search.search(query, n=15)
        except FileNotFoundError as e:
            error = "La base vectorielle n'est pas disponible. Exécutez build_vector_store.py dans le dossier Mairie."
        except Exception as e:
            error = str(e)
    return render(request, "search/index.html", {
        "query": query,
        "results": results,
        "error": error,
        "base_available": vector_search.is_available(),
    })
