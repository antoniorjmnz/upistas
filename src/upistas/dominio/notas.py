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
        r"\bescalar\s+(?:a\s+)?revision\s+humana\b",
        r"\b(?:registrar|clasificar|marcar)\s+(?:(?:la\s+)?(?:factura|decision)\s+)?(?:como\s+)?(?:pagar|no_pagar|escalar)\b",
    ],
    "pide_saltar_regla": [
        r"\b(?:paga(?:r|d|lo)?|pague(?:n)?|abona(?:r)?|abone)\b.{0,80}\b(?:aunque|incluso si|aun si)\b.{0,80}(?:no (?:cuadr|coincid)|falt[ae]|invalid|discrepanc|pagad)",
        r"no (debe |deben )?(recalcul|bloquear|procede contrastar|contrastar|comprobar|validar|consultar)",
        r"\bignor(?:a|ar|e)\b.{0,80}\b(?:erp|iva|iban|nif|importe|total|fecha|discrepancia|regla|control)",
        r"\bsin (?:escalado|comprobar|validar|contrastar)\b", r"proced(a|ase) al alta",
        r"\bpagad[oa]\b.{0,140}(?:procedase al abono|continuese el pago|pagar|pagarse)",
        r"tomese (?:como|la) (?:fecha de emision|fecha de la factura|fecha|base|total|importe)",
        r"debe tomarse como", r"tomarla como valida", r"validarse por razon social",
        r"no procede contrastar", r"(?:diferencia|discrepancia).{0,100}(?:ya esta aprobad|aprobad[oa]s? (?:de palabra|por el))",
        r"de alta con los datos", r"no registr(?:es|ar|e).{0,60}(?:discrepancia|error|diferencia)",
    ],
    "info_negocio": [
        r"anulad", r"no procede pago", r"en revision", r"cumplimiento", r"cuenta bancaria", r"nuevo numero de cuenta",
        r"entidad bancaria", r"cambiad[oa]", r"migracion", r"reemision", r"pendiente de pago", r"regimen especial",
        r"cuenta de abono", r"no coincident",
        r"bonificacion", r"recargo", r"dos nif", r"reestructuracion", r"contrato marco", r"alta reciente",
        r"verificacion cruzada", r"fecha de recepcion", r"sello de entrada",
    ],
    "urgencia": [
        r"(?<!transporte )urgente", r"inmediat", r"cada minuto", r"depende (el futuro|que)", r"paz mundial", r"salvate", r"pierde una hora",
    ],
}
_COMPILADOS = {cat: [re.compile(p) for p in pats] for cat, pats in _PATRONES.items()}

# «Condiciones de pago: 30 días desde la fecha de factura» en los idiomas del lote 2. Detrás de los días solo se
# admiten palabras de esta lista (fecha, factura, emisión, from the invoice date...): cualquier otra descarta la frase.
_ETIQUETAS_PLAZO = (
    r"condiciones de pago|condicions de pagament|condicoes de pagamento|conditions de paiement|termini di pagamento|"
    r"payment terms|terms of payment|zahlungsbedingungen|zahlungsziel|zahlungsfrist|plazo de pago|forma de pago|"
    r"vencimiento|pago|pagament|pagamento|paiement|payment|zahlung|zahlbar"
)
_PLAZO = re.compile(
    rf"^(?:{_ETIQUETAS_PLAZO})\s*:?\s*(?:a|en|net|netto|entro|innerhalb von|dins de|em|a los|within|sous|dentro de)?\s*"
    r"\d{1,3}\s*(?:dias|dies|days|jours|giorni|tage|tagen)(?P<cola>[a-z'. ]*)$"
)
_COLA_PLAZO = frozenset(
    "desde a partir de del la el fecha factura emision recepcion f ff neto fin mes "
    "from after of the invoice issue date receipt net end month eom "
    "compter apres le date d emission facture reception mois "
    "da data fatura emissao apos recepcao liquido fim "
    "des dies emissio recepcio final "
    "dalla dal dopo della di fattura emissione ricevimento ricezione netto fine mese "
    "ab nach rechnungsdatum rechnungseingang rechnung datum erhalt der dem ohne abzug rein".split()
)
_PIE_INOFENSIVO = re.compile(r"^documento generado (?:automaticamente )?por el sistema de facturacion(?: del proveedor)?$")


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, para que 'procédase' y 'procedase' sean lo mismo."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def controles_invisibles(texto: str) -> tuple[str, ...]:
    return tuple(sorted({f"U+{ord(c):04X}" for c in texto
                         if unicodedata.category(c) in ("Cf", "Cc") and c not in "\n\r\t"}))


def clasificar(texto: str) -> tuple[str, ...]:
    t = normalizar(texto)
    categorias = tuple(cat for cat, pats in _COMPILADOS.items() if any(p.search(t) for p in pats))
    return categorias or ("otra",)


def solo_plazo_de_pago(texto: str) -> bool:
    """«Condiciones de pago: 30 días desde la fecha de factura» y nada más: un dato del proveedor, no una instrucción.

    Admite el pie «Documento generado por el sistema de facturación del proveedor» (lote 2). Cualquier otra
    frase (cambiar la cuenta, pagar ya, saltarse una regla...) hace que la nota no sea solo un plazo.
    """
    frases = [f.strip() for f in re.split(r"[.;]\s+|[.;]$", normalizar(texto)) if f.strip()]
    plazos = 0
    for frase in frases:
        plazo = _PLAZO.match(frase)
        if plazo and all(palabra in _COLA_PLAZO for palabra in re.findall(r"[a-z]+", plazo.group("cola"))):
            plazos += 1
        elif not _PIE_INOFENSIVO.match(frase):
            return False
    return plazos > 0


def nota(texto: str) -> Nota:
    return Nota(texto=" ".join(texto.split()), categorias=clasificar(texto))


def sospechosas(notas: tuple[Nota, ...]) -> tuple[Nota, ...]:
    """Las que intentan influir en la decisión (todo menos 'otra' e 'info_negocio' a secas)."""
    return tuple(n for n in notas if any(c in ("dirigida_al_sistema", "pide_saltar_regla", "urgencia") for c in n.categorias))
