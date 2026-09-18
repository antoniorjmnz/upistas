from upistas.dominio.modelos import Comprobacion
from upistas.dominio.reglas import regla


@regla("R4_fecha")
def fecha_valida_y_no_futura(factura, refs, params):
    if factura.fecha is None:
        return Comprobacion("R4_fecha", False, "Fecha ilegible o inválida")
    if factura.fecha > refs.hoy:
        return Comprobacion("R4_fecha", False, f"Fecha futura: {factura.fecha.isoformat()}")
    return Comprobacion("R4_fecha", True)
