"""RepositorioDecisiones sobre nuestra base de datos: ejecuciones, decisiones y la memoria de pagos."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from upistas.puertos import DecisionGuardada, Ejecucion


def _ahora() -> datetime:
    return datetime.now().astimezone()


class RepositorioDecisionesDjango:
    def iniciar_ejecucion(self, lote: str, norma: str, version_erp: str, version_excel: str, hardware: dict) -> Ejecucion:
        from web.panel.models import Ejecucion as M

        m = M.objects.create(lote=lote, norma=norma, version_erp=version_erp, version_excel=version_excel, inicio=_ahora(), hardware=hardware)
        return self._ejecucion(m)

    def guardar_decisiones(self, ejecucion_id: int, decisiones: Sequence[DecisionGuardada]) -> None:
        from django.db import transaction

        from web.panel.models import Decision, Documento, Ejecucion as M

        ejecucion = M.objects.get(pk=ejecucion_id)
        docs = {d.file_id: d for d in Documento.objects.filter(lote=ejecucion.lote)}
        with transaction.atomic():
            Decision.objects.filter(ejecucion=ejecucion).delete()
            Decision.objects.bulk_create(
                Decision(
                    ejecucion=ejecucion, documento=docs[d.file_id], resultado=d.resultado, motivo=d.motivo,
                    pedido=d.pedido or "", metodo=d.metodo, outcome=d.outcome, notas=list(d.notas), alertas=list(d.alertas),
                )
                for d in decisiones if d.file_id in docs
            )

    def terminar_ejecucion(self, ejecucion_id: int, resumen: dict) -> Ejecucion:
        from web.panel.models import Ejecucion as M

        m = M.objects.get(pk=ejecucion_id)
        m.fin, m.estado, m.resumen = _ahora(), "terminada", resumen
        m.save(update_fields=["fin", "estado", "resumen"])
        return self._ejecucion(m)

    def ejecuciones(self, lote: str | None = None) -> list[Ejecucion]:
        from web.panel.models import Ejecucion as M

        qs = M.objects.all()
        if lote:
            qs = qs.filter(lote=lote)
        return [self._ejecucion(m) for m in qs]

    def decisiones(self, ejecucion_id: int) -> list[DecisionGuardada]:
        from web.panel.models import Decision

        return [
            DecisionGuardada(
                file_id=d.documento.file_id, resultado=d.resultado, motivo=d.motivo, pedido=d.pedido or None,
                metodo=d.metodo, outcome=d.outcome, notas=tuple(d.notas or []), alertas=tuple(d.alertas or []),
            )
            for d in Decision.objects.filter(ejecucion_id=ejecucion_id).select_related("documento")
        ]

    def pedidos_aprobados(self, excepto_lote: str) -> frozenset[str]:
        from web.panel.models import Decision, Ejecucion as M, RevisionHumana

        aprobados: set[str] = set()
        lotes = M.objects.filter(estado="terminada").exclude(lote=excepto_lote).values_list("lote", flat=True).distinct()
        for lote in lotes:
            ultima = M.objects.filter(lote=lote, estado="terminada").first()  # la más reciente
            aprobados.update(
                Decision.objects.filter(ejecucion=ultima, resultado="PAGAR").exclude(pedido="").values_list("pedido", flat=True)
            )
        aprobados.update(
            p for p in RevisionHumana.objects.filter(resultado="PAGAR", decision__isnull=False)
            .exclude(decision__pedido="").values_list("decision__pedido", flat=True)
        )
        return frozenset(aprobados)

    @staticmethod
    def _ejecucion(m) -> Ejecucion:
        return Ejecucion(
            id=m.id, lote=m.lote, norma=m.norma, version_erp=m.version_erp, version_excel=m.version_excel,
            inicio=m.inicio, fin=m.fin, estado=m.estado, hardware=dict(m.hardware or {}), resumen=dict(m.resumen or {}),
        )
