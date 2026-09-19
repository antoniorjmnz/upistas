"""Consultas que comparten varias pantallas. Solo lectura sobre nuestra base de datos.

Vocabulario: un *lote* se procesa en varias *ejecuciones* (cada vez que cambian los datos o la norma);
la que vale es la última terminada. Cada ejecución tiene una *decisión* por documento. La *lectura*
de un documento se busca por su huella (sha256), no por nombre: el mismo contenido se lee una vez.
"""
from __future__ import annotations

from collections.abc import Iterable

from django.db.models import QuerySet

from upistas.adaptadores.persistencia.django_decisiones import RepositorioDecisionesDjango
from upistas.aplicacion.lote import Cambio, comparar
from web.panel.models import Decision, Ejecucion, Lectura, RevisionHumana

CLASE = {"PAGAR": "bien", "NO_PAGAR": "mal", "ESCALAR": "ojo"}
ETIQUETA = {"PAGAR": "Pagar", "NO_PAGAR": "No pagar", "ESCALAR": "Revisar"}


def lotes() -> list[str]:
    return list(Ejecucion.objects.filter(estado="terminada").order_by("lote").values_list("lote", flat=True).distinct())


def ultima_ejecucion(lote: str | None = None) -> Ejecucion | None:
    """La ejecución terminada más reciente (del lote, o de cualquiera)."""
    qs = Ejecucion.objects.filter(estado="terminada")
    if lote:
        qs = qs.filter(lote=lote)
    return qs.first()


def anterior_a(ejecucion: Ejecucion) -> Ejecucion | None:
    return Ejecucion.objects.filter(lote=ejecucion.lote, estado="terminada", inicio__lt=ejecucion.inicio).first()


def decisiones_de(ejecucion: Ejecucion) -> QuerySet[Decision]:
    return Decision.objects.filter(ejecucion=ejecucion).select_related("documento")


def lecturas_por_sha(shas: Iterable[str]) -> dict[str, Lectura]:
    """La lectura más reciente de cada contenido."""
    return {l.sha256: l for l in Lectura.objects.filter(sha256__in=set(shas)).order_by("creada")}


def campos(lectura: Lectura | None) -> dict:
    """Los valores leídos, planos: {"nif": "B46102331", "total": 2489.99, ...}. Vacío si no se leyó."""
    if lectura is None or not lectura.extraida:
        return {}
    return {nombre: (campo or {}).get("valor") for nombre, campo in lectura.extraida.get("campos", {}).items()}


def revisiones_por_documento(lote: str) -> dict[int, RevisionHumana]:
    """La última revisión humana de cada documento del lote, por id de documento."""
    ultimas: dict[int, RevisionHumana] = {}
    for r in RevisionHumana.objects.filter(documento__lote=lote).order_by("cuando", "id"):
        ultimas[r.documento_id] = r
    return ultimas


def pendientes_de_revision(ejecucion: Ejecucion) -> QuerySet[Decision]:
    """Escaladas en esa ejecución sobre las que Alberto no ha dicho nada todavía."""
    revisados = RevisionHumana.objects.filter(documento__lote=ejecucion.lote).values_list("documento_id", flat=True)
    return decisiones_de(ejecucion).filter(resultado="ESCALAR").exclude(documento_id__in=revisados)


def cambios_respecto_a_la_anterior(ejecucion: Ejecucion) -> tuple[Ejecucion | None, list[Cambio]]:
    """Qué facturas cambiaron de resultado respecto a la ejecución anterior del mismo lote."""
    anterior = anterior_a(ejecucion)
    if anterior is None:
        return None, []
    repo = RepositorioDecisionesDjango()
    return anterior, comparar(repo.decisiones(anterior.id), repo.decisiones(ejecucion.id))
