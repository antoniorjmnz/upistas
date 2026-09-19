"""«Importar datos»: subir un fichero de proveedores o de pedidos, verlo fila a fila y aplicarlo."""
from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from web.panel import importaciones

TOPE_BYTES = 10 * 1024 * 1024  # un fichero de altas de La Caja no llega ni a 1 MB


def importar(request: HttpRequest) -> HttpResponse:
    """Paso 1: elegir los ficheros. Se parsean, se guardan aparte y se pasa a la vista previa."""
    if request.method == "POST":
        return _leer_y_guardar(request)
    return render(request, "panel/importar.html", {"ultimas": importaciones.ultimas()})


def vista_previa(request: HttpRequest, token: str) -> HttpResponse:
    """Paso 2: qué es nuevo, qué cambia y qué no vale. Paso 3: aplicar solo lo válido, o cancelar."""
    ficheros = importaciones.cargar(token)
    if ficheros is None:
        messages.warning(request, "Esa vista previa ya no está. Vuelva a elegir los ficheros.", extra_tags="ojo")
        return redirect("panel:proveedor_importar")
    if request.method == "POST":
        if request.POST.get("accion") != "aplicar":
            importaciones.borrar(token)
            messages.success(request, "No se ha importado nada.", extra_tags="bien")
            return redirect("panel:proveedor_importar")
        hecho = importaciones.aplicar(ficheros)
        importaciones.borrar(token)  # después, no antes: si aplicar falla, la vista previa sigue ahí
        messages.success(request, _resultado(hecho), extra_tags="bien")
        return redirect("panel:proveedores")
    return render(request, "panel/importar_previa.html", {"vista": importaciones.previsualizar(ficheros), "token": token})


def _leer_y_guardar(request: HttpRequest) -> HttpResponse:
    subidos = request.FILES.getlist("ficheros")
    if not subidos:
        messages.error(request, "No ha elegido ningún fichero.", extra_tags="mal")
        return redirect("panel:proveedor_importar")
    ficheros = [_leer(f) for f in subidos]
    if all(f.tipo is None for f in ficheros):
        for f in ficheros:
            messages.error(request, f.aviso, extra_tags="mal")
        return redirect("panel:proveedor_importar")
    respuesta = redirect(reverse("panel:proveedor_importar_previa", args=[importaciones.guardar(ficheros)]))
    respuesta.status_code = 303  # recargar la vista previa no vuelve a subir nada
    return respuesta


def _leer(subido) -> importaciones.Fichero:
    if subido.size > TOPE_BYTES:
        return importaciones.Fichero(subido.name, None, aviso=(
            f"«{subido.name}» pesa más de 10 MB. Un fichero de proveedores o de pedidos no llega ni a 1 MB: "
            "compruebe que es el fichero correcto."))
    return importaciones.leer(subido.name, subido.read())


def _resultado(hecho) -> str:
    partes = [f"{hecho.nuevos} nuevo{'s' if hecho.nuevos != 1 else ''}", f"{hecho.cambiados} cambiado{'s' if hecho.cambiados != 1 else ''}"]
    if hecho.invalidos:
        partes.append(f"{hecho.invalidos} fila{'s' if hecho.invalidos != 1 else ''} sin importar")
    return f"Importado {hecho.ficheros}: {', '.join(partes)}."
