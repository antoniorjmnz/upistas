from upistas.dominio.modelos import Comprobacion
from upistas.dominio.reglas import regla


@regla("R4_fecha")
def fecha_valida_y_no_futura(factura, refs, params):
    if factura.fecha is None:
        segura = "fecha" in factura.ausentes  # el lector la leyó bien y no es una fecha real (31/02)
        return Comprobacion("R4_fecha", False, "Fecha inválida o ausente en el documento" if segura else "Fecha ilegible o inválida")
    if factura.fecha > refs.hoy:
        return Comprobacion("R4_fecha", False, f"Fecha futura: {factura.fecha.isoformat()}")
    return Comprobacion("R4_fecha", True)
