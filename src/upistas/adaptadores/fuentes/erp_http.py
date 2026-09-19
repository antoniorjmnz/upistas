"""Cliente del bridge HTTP del ERP de Alberto (2009). Solo lectura.

Cómo se porta el bridge (MANUAL_ERP_2009.md y alberto_erp.py), y cómo lo tratamos:
- XML en ISO-8859-1, fechas DD/MM/AAAA, importes 12.874,40.
- ORA-00600 (HTTP 500) en una de cada diez consultas: se reintenta la misma consulta.
- ERP-429 si pasamos de 10 peticiones/s, y las rechazadas también cuentan: se espera lo que
  diga Retry-After y, para no llegar ahí, vamos a un ritmo máximo por debajo del límite.
- Sesiones de 15 minutos o 300 consultas (SES-401): se vuelve a identificar y se sigue.
- 20 asientos por página y en desorden: se descargan todas y se comprueba el total.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from upistas.dominio.importes import parse_fecha, parse_importe
from upistas.dominio.modelos import Asiento
from upistas.puertos import DescargaERP, ErrorERP, EstadisticasDescarga


@dataclass
class _Contadores:
    peticiones: int = 0
    reintentos_ora: int = 0
    esperas_429: int = 0
    relogins: int = 0
    errores_red: int = 0


class ClienteErpHttp:
    def __init__(
        self,
        base_url: str,
        usuario: str,
        clave: str,
        *,
        peticiones_por_segundo: float = 8.0,
        max_intentos: int = 8,
        max_errores_red: int = 3,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.usuario = usuario
        self.clave = clave
        self.intervalo = 1.0 / peticiones_por_segundo
        self.max_intentos = max_intentos
        self.max_errores_red = max_errores_red
        self.timeout = timeout
        self.transport = transport
        self.dormir = dormir
        self.reloj = reloj

    # --- API pública -------------------------------------------------------------------------

    def descargar(self) -> DescargaERP:
        inicio = self.reloj()
        self._c = _Contadores()
        self._ultima_peticion = 0.0
        with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as http:
            self._http = http
            self._token = None
            estado = self._xml(self._pedir("GET", "/erp/estado", autenticada=False))
            primera = self._xml(self._pedir("GET", "/erp/asientos", params={"pagina": 1}))
            total = int(primera.findtext("meta/total"))
            paginas = int(primera.findtext("meta/paginas"))
            asientos = self._asientos_de(primera)
            for pagina in range(2, paginas + 1):
                asientos += self._asientos_de(self._xml(self._pedir("GET", "/erp/asientos", params={"pagina": pagina})))

        ids = {a.id for a in asientos}
        if len(asientos) != total or len(ids) != total:
            raise ErrorERP(f"Descarga incompleta: el ERP dice {total} asientos y han llegado {len(asientos)} ({len(ids)} distintos)")
        return DescargaERP(
            asientos=tuple(asientos),
            lote2_cargado=(estado.findtext("actualizacion_cargada") or "").strip().upper() == "SI",
            estadisticas=EstadisticasDescarga(
                peticiones=self._c.peticiones,
                reintentos_ora=self._c.reintentos_ora,
                esperas_429=self._c.esperas_429,
                relogins=self._c.relogins,
                errores_red=self._c.errores_red,
                segundos=round(self.reloj() - inicio, 3),
            ),
        )

    # --- fontanería ---------------------------------------------------------------------------

    def _pedir(self, metodo: str, ruta: str, *, autenticada: bool = True, params: dict | None = None, data: dict | None = None) -> httpx.Response:
        errores_red_seguidos = 0
        for _ in range(self.max_intentos):
            if autenticada and self._token is None:
                self._login()
            self._a_ritmo()
            headers = {"X-ERP-Token": self._token} if autenticada else {}
            self._c.peticiones += 1
            try:
                r = self._http.request(metodo, ruta, params=params, data=data, headers=headers)
            except httpx.TransportError as exc:
                self._c.errores_red += 1
                errores_red_seguidos += 1
                if errores_red_seguidos >= self.max_errores_red:
                    raise ErrorERP(f"El ERP no responde en {self.base_url} ({type(exc).__name__})") from exc
                self.dormir(1.0)
                continue
            codigo = self._codigo_erp(r)
            if r.status_code == 200:
                return r
            if r.status_code == 500 or codigo == "ORA-00600":
                self._c.reintentos_ora += 1
                continue
            if r.status_code == 429 or codigo == "ERP-429":
                self._c.esperas_429 += 1
                self.dormir(float(r.headers.get("Retry-After") or 1))
                continue
            if (r.status_code == 401 or codigo == "SES-401") and autenticada:
                self._c.relogins += 1
                self._token = None
                continue
            raise ErrorERP(f"{metodo} {ruta} → {r.status_code} {codigo or ''}".strip())
        raise ErrorERP(f"{metodo} {ruta}: sin respuesta válida tras {self.max_intentos} intentos")

    def _login(self) -> None:
        r = self._pedir("POST", "/erp/login", autenticada=False, data={"usuario": self.usuario, "clave": self.clave})
        token = self._xml(r).findtext("token")
        if not token:
            raise ErrorERP("El ERP no devolvió token de sesión")
        self._token = token.strip()

    def _a_ritmo(self) -> None:
        espera = self._ultima_peticion + self.intervalo - self.reloj()
        if espera > 0:
            self.dormir(espera)
        self._ultima_peticion = self.reloj()

    @staticmethod
    def _xml(r: httpx.Response) -> ET.Element:
        try:
            return ET.fromstring(r.content)  # respeta el encoding ISO-8859-1 que declara el XML
        except ET.ParseError as exc:
            raise ErrorERP(f"Respuesta del ERP ilegible: {exc}") from exc

    @staticmethod
    def _codigo_erp(r: httpx.Response) -> str | None:
        if r.status_code == 200 or "xml" not in r.headers.get("content-type", ""):
            return None
        try:
            return (ET.fromstring(r.content).findtext("codigo") or "").strip() or None
        except ET.ParseError:
            return None

    @staticmethod
    def _asientos_de(raiz: ET.Element) -> list[Asiento]:
        asientos = []
        for nodo in raiz.iter("asiento"):
            importe = parse_importe(nodo.findtext("importe") or "")
            if importe is None:
                raise ErrorERP(f"Importe ilegible en el asiento {nodo.findtext('id')}")
            asientos.append(
                Asiento(
                    id=(nodo.findtext("id") or "").strip(),
                    pedido=(nodo.findtext("pedido") or "").strip(),
                    proveedor_id=(nodo.findtext("proveedor") or "").strip(),
                    nif=(nodo.findtext("nif") or "").strip(),
                    importe=importe,
                    fecha=parse_fecha(nodo.findtext("fecha") or ""),
                    estado=(nodo.findtext("estado") or "").strip().upper(),
                )
            )
        return asientos
