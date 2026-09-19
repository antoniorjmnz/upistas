"""AlmacenERP sobre la base de datos de la web: copia versionada de los asientos e historial."""
from __future__ import annotations

from upistas.dominio.modelos import Asiento
from upistas.puertos import EstadisticasDescarga, Sincronizacion


class AlmacenERPDjango:
    """Los modelos se importan dentro de cada método: Django tiene que estar configurado antes."""

    def registrar(self, sincronizacion: Sincronizacion, asientos: tuple[Asiento, ...] | None) -> None:
        from django.db import transaction

        from web.panel.models import AsientoERP, SincronizacionERP, VersionERP

        s = sincronizacion
        e = s.estadisticas
        with transaction.atomic():
            version = None
            if s.ok and s.version:
                version, creada = VersionERP.objects.get_or_create(
                    version=s.version,
                    defaults={"creada": s.fin, "n_asientos": s.n_asientos, "lote2_cargado": s.lote2_cargado},
                )
                if creada and asientos:
                    AsientoERP.objects.bulk_create(
                        AsientoERP(
                            version=version, asiento_id=a.id, pedido=a.pedido, proveedor_id=a.proveedor_id,
                            nif=a.nif, importe=a.importe, fecha=a.fecha, estado=a.estado,
                        )
                        for a in asientos
                    )
            SincronizacionERP.objects.create(
                inicio=s.inicio, fin=s.fin, ok=s.ok, version=version, n_asientos=s.n_asientos,
                lote2_cargado=s.lote2_cargado, peticiones=e.peticiones, reintentos_ora=e.reintentos_ora,
                esperas_429=e.esperas_429, relogins=e.relogins, errores_red=e.errores_red, segundos=e.segundos,
                error=s.error or "", nuevos=s.nuevos, modificados=s.modificados, eliminados=s.eliminados,
            )

    def asientos(self, version: str | None = None) -> list[Asiento]:
        from web.panel.models import AsientoERP

        if version is None:
            ultima = self.ultima()
            if ultima is None:
                return []
            version = ultima.version
        return [
            Asiento(id=a.asiento_id, pedido=a.pedido, proveedor_id=a.proveedor_id, nif=a.nif,
                    importe=a.importe, fecha=a.fecha, estado=a.estado)
            for a in AsientoERP.objects.filter(version_id=version)
        ]

    def ultima(self, solo_correctas: bool = True) -> Sincronizacion | None:
        from web.panel.models import SincronizacionERP

        qs = SincronizacionERP.objects.all()
        if solo_correctas:
            qs = qs.filter(ok=True)
        m = qs.first()
        if m is None:
            return None
        return Sincronizacion(
            inicio=m.inicio, fin=m.fin, ok=m.ok, version=m.version_id, n_asientos=m.n_asientos,
            lote2_cargado=m.lote2_cargado, error=m.error or None,
            estadisticas=EstadisticasDescarga(
                peticiones=m.peticiones, reintentos_ora=m.reintentos_ora, esperas_429=m.esperas_429,
                relogins=m.relogins, errores_red=m.errores_red, segundos=m.segundos,
            ),
            nuevos=m.nuevos, modificados=m.modificados, eliminados=m.eliminados,
        )
