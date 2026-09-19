"""Las pocas cosas que el asistente puede hacer por Alberto, siempre con su confirmación.

El modelo solo PROPONE (`proponer`): comprueba que la acción existe y que sus datos apuntan a algo real,
y devuelve una tarjeta con un token firmado (django.core.signing, caduca a los 10 minutos). Nada cambia
hasta que Alberto pulsa «Confirmar»: entonces la vista lee el token (`leer_token`) y llama a `ejecutar`,
que vuelve a comprobar que el tipo está en la lista blanca y deja la fila en `AccionAsistente`.

Fuera de la lista, y por tanto imposibles aunque el token venga firmado: pagar o no pagar una factura,
crear o borrar proveedores o pedidos, subir o repasar lotes y tocar el ERP.
"""
from __future__ import annotations

from django.core import signing
from django.urls import reverse

from web.panel import consultas
from web.panel.models import AccionAsistente, Decision, Pedido

CADUCIDAD_S = 10 * 60
MAX_TEXTO = 500
_SAL = "asistente.accion"

# Lista blanca: solo estos tipos existen. Quien no está aquí no se propone ni se ejecuta.
TIPOS = {
    "marcar_pedido_para_revisar": "Marcar el pedido {pedido} para que sus facturas se revisen a mano",
    "quitar_marca_de_pedido": "Quitar la marca de revisar del pedido {pedido}",
    "apuntar_nota_en_pedido": "Apuntar en el pedido {pedido} la nota «{nota}»",
    "apuntar_comentario_en_factura": "Apuntar en la factura {file_id} el comentario «{comentario}» (sin decidirla)",
}


class AccionInvalida(Exception):
    """La acción no existe o sus datos no apuntan a nada real. El mensaje se le enseña al modelo."""


def _texto(datos: dict, clave: str) -> str:
    texto = str(datos.get(clave) or "").strip()
    if not texto:
        raise AccionInvalida(f"falta «{clave}»")
    if len(texto) > MAX_TEXTO:
        raise AccionInvalida(f"«{clave}» no puede pasar de {MAX_TEXTO} letras")
    return texto


def _pedido(datos: dict) -> Pedido:
    canon = consultas._canon_pedido(str(datos.get("pedido") or ""))
    if not canon:
        raise AccionInvalida("falta el número de pedido (PO-AAAA-NNNN)")
    pedido = next((p for p in Pedido.objects.select_related("proveedor") if consultas._canon_pedido(p.numero) == canon), None)
    if pedido is None:
        raise AccionInvalida(f"el pedido {datos.get('pedido')} no está en el maestro")
    return pedido


def _factura_escalada(datos: dict) -> Decision:
    file_id = str(datos.get("file_id") or "").strip()
    if not file_id:
        raise AccionInvalida("falta el nombre del fichero de la factura")
    ejecucion = consultas.ultima_ejecucion(str(datos.get("lote") or "") or None)
    if ejecucion is None:
        raise AccionInvalida("todavía no se ha repasado ningún lote")
    decision = consultas.decisiones_de(ejecucion).filter(documento__file_id=file_id).first()
    if decision is None:
        raise AccionInvalida(f"la factura {file_id} no está en el último repaso")
    if decision.resultado != "ESCALAR":
        raise AccionInvalida(f"la factura {file_id} no está para revisar: solo se comentan las escaladas")
    return decision


def _normalizar(tipo: str, datos: dict) -> dict:
    """Los datos con los que se firma y se ejecuta: comprobados y sin nada de más."""
    if tipo not in TIPOS:
        raise AccionInvalida(f"la acción «{tipo}» no existe; solo puedo proponer: {', '.join(TIPOS)}")
    if tipo in ("marcar_pedido_para_revisar", "quitar_marca_de_pedido"):
        return {"pedido": _pedido(datos).numero}
    if tipo == "apuntar_nota_en_pedido":
        return {"pedido": _pedido(datos).numero, "nota": _texto(datos, "nota")}
    decision = _factura_escalada(datos)
    return {"lote": decision.documento.lote, "file_id": decision.documento.file_id, "comentario": _texto(datos, "comentario")}


def firmar(tipo: str, datos: dict) -> str:
    return signing.dumps({"tipo": tipo, "datos": datos}, salt=_SAL)


def leer_token(token: str) -> tuple[str, dict]:
    """El tipo y los datos que se firmaron. Lanza signing.BadSignature (o SignatureExpired) si no valen."""
    carga = signing.loads(token, salt=_SAL, max_age=CADUCIDAD_S)
    tipo, datos = carga.get("tipo"), carga.get("datos")
    if tipo not in TIPOS or not isinstance(datos, dict):
        raise signing.BadSignature("el token no lleva una acción de la lista")
    return tipo, datos


def proponer(tipo: str, datos: dict | None) -> dict:
    """Lo que el modelo puede hacer: una propuesta firmada que Alberto confirma o no. No cambia nada."""
    try:
        limpios = _normalizar(str(tipo or ""), dict(datos or {}))
    except AccionInvalida as e:
        return {"error": str(e)}
    return {
        "propuesta": {
            "tipo": tipo,
            "datos": limpios,
            "descripcion": TIPOS[tipo].format(**limpios),
            "token": firmar(tipo, limpios),
        },
        "aviso": "No se ha hecho nada todavía: Alberto tiene que pulsar Confirmar en la tarjeta que ve.",
    }


def ejecutar(tipo: str, datos: dict) -> AccionAsistente:
    """La acción confirmada por Alberto. Solo desde la vista de confirmación, con el token ya comprobado."""
    if tipo not in TIPOS:
        raise AccionInvalida(f"la acción «{tipo}» no está en la lista")
    try:
        limpios = _normalizar(tipo, datos)
        resultado = _hacer(tipo, limpios)
        ok = True
    except AccionInvalida as e:
        limpios, resultado, ok = dict(datos), f"No se pudo: {e}", False
    return AccionAsistente.objects.create(tipo=tipo, datos=limpios, resultado=resultado, ok=ok)


def _hacer(tipo: str, datos: dict) -> str:
    if tipo == "marcar_pedido_para_revisar":
        pedido = _pedido(datos)
        Pedido.objects.filter(pk=pedido.pk).update(revisar=True)
        return f"El pedido {pedido.numero} queda marcado para revisar"
    if tipo == "quitar_marca_de_pedido":
        pedido = _pedido(datos)
        Pedido.objects.filter(pk=pedido.pk).update(revisar=False)
        return f"El pedido {pedido.numero} ya no está marcado para revisar"
    if tipo == "apuntar_nota_en_pedido":
        pedido = _pedido(datos)
        pedido.nota = f"{pedido.nota}\n{datos['nota']}".strip()
        pedido.save(update_fields=["nota", "actualizado"])
        return f"Nota apuntada en el pedido {pedido.numero}: «{datos['nota']}»"
    decision = _factura_escalada(datos)
    return f"Comentario apuntado en la factura {decision.documento.file_id}: «{datos['comentario']}»"


def enlace(accion: AccionAsistente) -> dict | None:
    """La pantalla donde se ve lo que se hizo, si la hay."""
    datos = accion.datos or {}
    if accion.tipo == "apuntar_comentario_en_factura" and datos.get("lote") and datos.get("file_id"):
        return {"titulo": f"Factura {datos['file_id']}", "url": reverse("panel:factura", args=[datos["lote"], datos["file_id"]])}
    if datos.get("pedido"):
        pedido = Pedido.objects.filter(numero=datos["pedido"]).first()
        if pedido is not None:
            return {"titulo": f"Pedido {pedido.numero}", "url": reverse("panel:proveedor", args=[pedido.proveedor_id])}
    return None


def comentarios_de_factura(lote: str, file_id: str) -> list[AccionAsistente]:
    """Los comentarios que Alberto apuntó desde el asistente en esa factura."""
    return list(AccionAsistente.objects.filter(
        tipo="apuntar_comentario_en_factura", ok=True, datos__lote=lote, datos__file_id=file_id,
    ).order_by("cuando", "id"))
