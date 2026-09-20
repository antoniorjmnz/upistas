from upistas.dominio.modelos import Comprobacion
from upistas.dominio.reglas import regla


@regla("R4_fecha")
def fecha_valida_y_no_futura(factura, refs, params):
    if factura.fecha is None:
        if "fecha" not in factura.ausentes:  # no se pudo leer: lo dice R0_lectura y no se da por incumplido
            return Comprobacion("R4_fecha", True, "No se contrasta: la fecha no se pudo leer")
        # El lector la leyó bien y no es una fecha real (31/02), o el documento no trae ninguna.
        detalle = f"Fecha imposible: {factura.fecha_texto}" if factura.fecha_texto else "La factura no trae fecha"
        return Comprobacion("R4_fecha", False, detalle)
    if factura.fecha > refs.hoy:
        return Comprobacion("R4_fecha", False, f"Fecha futura: {factura.fecha:%d/%m/%Y}")
    return Comprobacion("R4_fecha", True)
