"""`ir_a`: la herramienta con la que el asistente lleva a Alberto a una pantalla de esta web.

Solo devuelve rutas de aquí (salen de `reverse`, nunca de lo que escriba el modelo), y los filtros que
acepta son los mismos que tienen las pantallas: resultado, proveedor del maestro, fechas, texto y lote.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.urls import reverse

from web.panel import consultas

PANTALLAS = {
    "inicio": "Hoy",
    "facturas": "Facturas",
    "revisar": "Para revisar",
    "factura": "una factura",
    "proveedores": "Proveedores",
    "proveedor": "un proveedor",
    "ejecuciones": "Registro de repasos",
    "erp": "Conexión con el ERP",
    "asientos": "Asientos del ERP",
    "importar": "Importar datos",
}
RESULTADOS = {"PAGAR": "PAGAR", "NO_PAGAR": "NO_PAGAR", "ESCALAR": "ESCALAR", "REVISAR": "ESCALAR"}
_SIN_FILTROS = {"inicio": "panel:inicio", "proveedores": "panel:proveedores", "ejecuciones": "panel:ejecuciones",
                "erp": "panel:conexion", "importar": "panel:proveedor_importar"}

_proveedor = consultas.buscar_proveedor  # por código (P001), NIF o trozo del nombre


def _filtros_de_lista(filtros: dict) -> tuple[dict, list[str]]:
    """Los parámetros que las listas de facturas entienden, comprobados uno a uno."""
    params: dict[str, str] = {}
    avisos: list[str] = []
    resultado = str(filtros.get("resultado") or "").upper().replace(" ", "_")
    if resultado:
        if resultado in RESULTADOS:
            params["resultado"] = RESULTADOS[resultado]
        else:
            avisos.append(f"resultado «{filtros.get('resultado')}» no existe: PAGAR, NO_PAGAR o ESCALAR")
    proveedor = str(filtros.get("proveedor") or "")
    if proveedor:
        p = _proveedor(proveedor)
        if p is None:
            avisos.append(f"no hay ningún proveedor «{proveedor}» en el maestro; se enseña sin ese filtro")
        else:
            params["proveedor"] = p.codigo
    for clave in ("desde", "hasta"):
        if filtros.get(clave):
            fecha = consultas.fecha_o_nada(str(filtros[clave]))
            if fecha is None:
                avisos.append(f"la fecha «{filtros[clave]}» no vale (AAAA-MM-DD)")
            else:
                params[clave] = fecha.isoformat()
    if filtros.get("texto"):
        params["q"] = str(filtros["texto"])[:100]
    lote = str(filtros.get("lote") or "").strip().lower().replace(" ", "")
    if lote:
        lotes = consultas.lotes()
        if lote in lotes:
            params["lote"] = lote
        else:
            avisos.append(f"no hay ningún lote «{filtros['lote']}» decidido; hay: {', '.join(lotes) or 'ninguno'}")
    return params, avisos


def ir_a(pantalla: str = "", filtros: dict | None = None) -> dict:
    """La dirección de una pantalla de esta web con sus filtros, o un error legible. Nunca sale fuera."""
    pantalla = str(pantalla or "").strip().lower()
    filtros = dict(filtros or {})
    if pantalla not in PANTALLAS:
        return {"error": f"la pantalla «{pantalla}» no existe; hay: {', '.join(PANTALLAS)}"}
    titulo = PANTALLAS[pantalla]
    avisos: list[str] = []

    if pantalla == "factura":
        file_id = str(filtros.get("file_id") or filtros.get("texto") or "").strip()
        if not file_id:
            return {"error": "para ir a una factura hace falta su file_id (nombre del fichero)"}
        encontradas = consultas.buscar_facturas(file_id, limite=2).get("encontradas") or []
        exacta = [f for f in encontradas if f["file_id"] == file_id] or encontradas
        if not exacta:
            return {"error": f"no hay ninguna factura «{file_id}» en el último repaso"}
        fila = exacta[0]
        return {"url": reverse("panel:factura", args=[fila["lote"], fila["file_id"]]), "titulo": f"Factura {fila['file_id']}"}

    if pantalla == "proveedor":
        p = _proveedor(str(filtros.get("proveedor") or filtros.get("texto") or ""))
        if p is None:
            return {"error": "no encuentro ese proveedor en el maestro (vale el código P001, el NIF o el nombre)"}
        return {"url": reverse("panel:proveedor", args=[p.id]), "titulo": p.nombre}

    if pantalla == "asientos":
        params = {"q": str(filtros.get("pedido") or filtros.get("texto") or "")[:100]} if (filtros.get("pedido") or filtros.get("texto")) else {}
        url = reverse("panel:asientos")
    elif pantalla in ("facturas", "revisar"):
        params, avisos = _filtros_de_lista(filtros)
        url = reverse("panel:facturas" if pantalla == "facturas" else "panel:cola")
        if pantalla == "revisar":
            params.pop("resultado", None)  # en Para revisar todas son escaladas
        nombre = dict(consultas.proveedores_para_filtro()).get(params.get("proveedor", ""))
        if nombre:
            titulo += f" de {nombre}"
        if params.get("resultado"):
            titulo += f" · {consultas.ETIQUETA[params['resultado']]}"
        if params.get("lote"):
            titulo += f" · {consultas.nombre_lote(params['lote'])}"
    else:
        params = {}
        url = reverse(_SIN_FILTROS[pantalla])

    salida = {"url": f"{url}?{urlencode(params)}" if params else url, "titulo": titulo}
    if avisos:
        salida["avisos"] = avisos
    return salida
