from __future__ import annotations

import math
import time
from xml.etree import ElementTree as ET

import httpx

from upistas.dominio.importes import parse_fecha, parse_importe
from upistas.dominio.modelos import Asiento


class ErpHTTP:
    def __init__(self, url, usuario, clave, *, transport=None, intervalo=0.12, dormir=time.sleep):
        self.url = url
        self.usuario = usuario
        self.clave = clave
        self.transport = transport
        self.intervalo = intervalo
        self.dormir = dormir
        self.token = ""
        self.ultima_consulta = 0.0

    def _solicitar(self, cliente, metodo, ruta, *, autenticar=True, **kwargs):
        for intento in range(5):
            espera = self.intervalo - (time.monotonic() - self.ultima_consulta)
            if espera > 0:
                self.dormir(espera)
            self.ultima_consulta = time.monotonic()
            try:
                respuesta = cliente.request(
                    metodo, ruta,
                    headers={"X-ERP-Token": self.token} if autenticar else {},
                    **kwargs,
                )
            except httpx.TransportError:
                if intento == 4:
                    raise ValueError(f"No se pudo conectar con el ERP en {self.url}") from None
                self.dormir(0.25 * 2 ** intento)
                continue

            try:
                raiz = ET.fromstring(respuesta.content)
            except ET.ParseError:
                raiz = None
            codigo = (raiz.findtext("codigo") or "").strip() if raiz is not None else ""
            if autenticar and (respuesta.status_code == 401 or codigo == "SES-401"):
                self._login(cliente)
                continue
            if respuesta.status_code == 429 or codigo == "ERP-429":
                try:
                    espera = float(respuesta.headers.get("Retry-After", "1"))
                except ValueError:
                    espera = 1.0
                self.dormir(espera if math.isfinite(espera) and espera >= 0 else 1.0)
                continue
            if respuesta.status_code >= 500 or codigo == "ORA-00600":
                self.dormir(0.25 * 2 ** intento)
                continue
            if respuesta.status_code >= 300 or codigo:
                raise ValueError(f"ERP: {codigo or respuesta.status_code} al consultar {ruta}")
            if raiz is None:
                raise ValueError(f"XML inválido del ERP en {ruta}")
            return raiz
        raise ValueError(f"ERP: se agotaron los reintentos en {ruta}")

    def _login(self, cliente):
        raiz = self._solicitar(
            cliente, "POST", "/erp/login", autenticar=False,
            data={"usuario": self.usuario, "clave": self.clave},
        )
        self.token = (raiz.findtext("token") or "").strip()
        if not self.token:
            raise ValueError("ERP: sesión sin token")

    def asientos(self) -> list[Asiento]:
        resultado = []
        ids, pedidos = set(), set()
        total, paginas, numero = None, 1, 1
        with httpx.Client(base_url=self.url, timeout=10, transport=self.transport) as cliente:
            self._login(cliente)
            while numero <= paginas:
                raiz = self._solicitar(cliente, "GET", "/erp/asientos", params={"pagina": numero})
                try:
                    meta_total = int(raiz.findtext("meta/total", ""))
                    meta_paginas = int(raiz.findtext("meta/paginas", ""))
                    meta_pagina = int(raiz.findtext("meta/pagina", ""))
                except ValueError:
                    raise ValueError("ERP: metadatos de paginación inválidos") from None
                if meta_pagina != numero or meta_total < 0 or meta_paginas < 1:
                    raise ValueError("ERP: página o totales inválidos")
                if total is not None and (meta_total != total or meta_paginas != paginas):
                    raise ValueError("ERP: los datos cambiaron durante la descarga; vuelve a ejecutar")
                total, paginas = meta_total, meta_paginas
                for nodo in raiz.findall(".//asiento"):
                    datos = {nombre: (nodo.findtext(nombre) or "").strip() for nombre in (
                        "id", "fecha", "proveedor", "nif", "pedido", "importe", "estado",
                    )}
                    fecha = parse_fecha(datos["fecha"])
                    importe = parse_importe(datos["importe"])
                    estado = datos["estado"].upper()
                    if not all(datos[k] for k in ("id", "proveedor", "pedido")) or fecha is None or importe is None or not importe.is_finite() or estado not in {"PENDIENTE", "PAGADA"}:
                        raise ValueError(f"ERP: asiento inválido {datos['id']}")
                    if datos["id"] in ids or datos["pedido"] in pedidos:
                        raise ValueError(f"ERP: asiento o pedido repetido {datos['id']}")
                    ids.add(datos["id"])
                    pedidos.add(datos["pedido"])
                    resultado.append(Asiento(
                        datos["id"], datos["pedido"], datos["proveedor"], datos["nif"].upper(),
                        importe, fecha, estado,
                    ))
                numero += 1
        if len(resultado) != total:
            raise ValueError(f"ERP: descarga incompleta, {len(resultado)} asientos de {total}")
        return resultado
