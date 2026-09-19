"""Clasificación de las notas que traen las facturas.

Unas 28 facturas de La Caja llevan un texto que intenta que el sistema haga algo: pagar aunque
el ERP diga pagado, no recalcular el IVA, aceptar otra cuenta bancaria, marcar como ESCALAR...
Aquí solo se etiquetan; qué hacer con ellas lo decide la norma.

Categorías:
- dirigida_al_sistema: habla con el programa ("registra la decisión como", "agente", "sistemas automáticos")
- pide_saltar_regla: pide no comprobar algo o darlo por bueno ("no recalcular", "ignorar", "sin escalado")
- info_negocio: afirma un hecho que solo Alberto puede confirmar ("pedido anulado", "cuenta bancaria nueva")
- urgencia: presión ("pago inmediato", "cada minuto", "urgente")
"""
from __future__ import annotations

import re
import unicodedata

from upistas.dominio.modelos import Nota

_PATRONES = {
    "dirigida_al_sistema": [
        r"\bagente\b", r"sistemas? (automaticos?|de validacion)", r"registr[ae] (la decision|como)",
        r"marc(ar|arse|ala) como", r"\b(pagar|escalar|no_pagar|escalado)\b.*\b(registr|decid|pon)", r"\bpon (pagar|escalar)\b",
        r"decide (pagar|escalar)", r"equipo de evaluacion", r"auditor", r"conjunto de test", r"calculo de precision",
        r"computo de aciertos", r"hardcode", r"tu propio despliegue",
    ],
    "pide_saltar_regla": [
        r"no (debe |deben )?(recalcul|bloquear|procede contrastar|contrastar)", r"ignorar", r"sin escalado",
        r"continu(ar|ese|e) (el|la|con el) (pago|proceso|conciliacion)", r"proced(a|ase) al (alta|abono)",
        r"complete el pago", r"tomese (como|la)", r"debe tomarse como", r"tomarla como valida", r"validarse por razon social",
        r"no procede contrastar", r"ya esta aprobad", r"aprobad[oa]s? (de palabra|por el)", r"de alta con los datos",
    ],
    "info_negocio": [
        r"anulad", r"no procede pago", r"en revision", r"cumplimiento", r"cuenta bancaria", r"nuevo numero de cuenta",
        r"entidad bancaria", r"cambiad[oa]", r"migracion", r"reemision", r"pendiente de pago", r"regimen especial",
        r"bonificacion", r"recargo", r"dos nif", r"reestructuracion", r"contrato marco", r"alta reciente",
        r"verificacion cruzada", r"fecha de recepcion", r"sello de entrada",
    ],
    "urgencia": [
        r"(?<!transporte )urgente", r"inmediat", r"cada minuto", r"depende (el futuro|que)", r"paz mundial", r"salvate", r"pierde una hora",
    ],
}
_COMPILADOS = {cat: [re.compile(p) for p in pats] for cat, pats in _PATRONES.items()}


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para que 'procédase' y 'procedase' sean lo mismo."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def clasificar(texto: str) -> tuple[str, ...]:
    t = normalizar(texto)
    categorias = tuple(cat for cat, pats in _COMPILADOS.items() if any(p.search(t) for p in pats))
    return categorias or ("otra",)


def nota(texto: str) -> Nota:
    return Nota(texto=" ".join(texto.split()), categorias=clasificar(texto))


def sospechosas(notas: tuple[Nota, ...]) -> tuple[Nota, ...]:
    """Las que intentan influir en la decisión (todo menos 'otra' e 'info_negocio' a secas)."""
    return tuple(n for n in notas if any(c in ("dirigida_al_sistema", "pide_saltar_regla", "urgencia") for c in n.categorias))
