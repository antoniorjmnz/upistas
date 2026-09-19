"""RepositorioLecturas sobre nuestra base de datos: documentos por lote y una lectura por contenido."""
from __future__ import annotations

from upistas.contracts.factura_extraida import FacturaExtraida
from upistas.puertos import RegistroLectura


class RepositorioLecturasDjango:
    def guardar(self, r: RegistroLectura) -> None:
        from django.db import transaction

        from web.panel.models import Documento, Lectura

        with transaction.atomic():
            Documento.objects.update_or_create(
                lote=r.lote, file_id=r.file_id,
                defaults={"ruta": r.ruta, "sha256": r.sha256, "bytes": r.bytes, "tipo": r.tipo, "paginas": r.paginas, "alertas": list(r.alertas)},
            )
            if not r.sha256:  # sin contenido que identificar (no existe, vacío): solo el documento
                return
            Lectura.objects.update_or_create(
                sha256=r.sha256,
                defaults={
                    "file_id": r.file_id, "lote": r.lote, "ok": r.leida,
                    "lector": r.extraida.lector or "" if r.extraida else "",
                    "metodo": r.metodo,
                    "extraida": r.extraida.model_dump(mode="json", exclude_none=True) if r.extraida else None,
                    "intentos": [list(i) for i in r.intentos],
                    "segundos": r.segundos, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                    "coste_eur": r.coste_eur, "modelo": r.modelo,
                },
            )

    def por_sha(self, sha256: str) -> RegistroLectura | None:
        from web.panel.models import Documento, Lectura

        lectura = Lectura.objects.filter(sha256=sha256).first()
        if lectura is None:
            return None
        doc = Documento.objects.filter(sha256=sha256).order_by("primera_vez").first()
        return self._registro(doc, lectura)

    def del_lote(self, lote: str) -> list[RegistroLectura]:
        from web.panel.models import Documento, Lectura

        docs = list(Documento.objects.filter(lote=lote))
        lecturas = {l.sha256: l for l in Lectura.objects.filter(sha256__in={d.sha256 for d in docs})}
        return [self._registro(d, lecturas.get(d.sha256)) for d in docs]

    @staticmethod
    def _registro(doc, lectura) -> RegistroLectura:
        extraida = None
        if lectura is not None and lectura.extraida:
            extraida = FacturaExtraida.model_validate({**lectura.extraida, "file_id": doc.file_id if doc else lectura.file_id})
        return RegistroLectura(
            lote=doc.lote if doc else lectura.lote,
            file_id=doc.file_id if doc else lectura.file_id,
            ruta=doc.ruta if doc else "",
            sha256=lectura.sha256 if lectura else doc.sha256,
            bytes=doc.bytes if doc else 0,
            tipo=doc.tipo if doc else "otro",
            paginas=doc.paginas if doc else 0,
            alertas=tuple(doc.alertas or []) if doc else (),
            extraida=extraida,
            intentos=tuple(tuple(i) for i in (lectura.intentos or [])) if lectura else (),
            segundos=lectura.segundos if lectura else 0.0,
            tokens_in=lectura.tokens_in if lectura else 0,
            tokens_out=lectura.tokens_out if lectura else 0,
            coste_eur=lectura.coste_eur if lectura else 0.0,
            modelo=lectura.modelo if lectura else "",
            cuando=lectura.creada if lectura else None,
        )
