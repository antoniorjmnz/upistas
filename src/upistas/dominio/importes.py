"""Importes y fechas tal como vienen en facturas, Excel y ERP."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def parse_importe(texto: str) -> Decimal | None:
    """'12.874,40' | '1498.30' | 'EUR 1,498.30' | '2.489,99 €' → Decimal."""
    s = re.sub(r"[^\d,.\-]", "", texto or "")
    if not s:
        return None
    ultimo_sep = max(s.rfind(","), s.rfind("."))
    if ultimo_sep != -1 and len(s) - ultimo_sep - 1 == 2:  # dos decimales tras el último separador
        entero, dec = s[:ultimo_sep], s[ultimo_sep + 1 :]
        s = re.sub(r"[,.]", "", entero) + "." + dec
    else:
        s = re.sub(r"[,.]", "", s)
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_fecha(texto: str) -> date | None:
    """'08/01/2026' | '2026-01-08' | '15 de enero de 2026' → date. None si no es válida."""
    t = (texto or "").strip().lower()
    try:
        if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", t):
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2}) de ([a-z]+) de (\d{4})", t):
            if m[2] in MESES:
                return date(int(m[3]), MESES[m[2]], int(m[1]))
    except ValueError:
        return None
    return None


def normaliza_iban(texto: str | None) -> str | None:
    return re.sub(r"\s", "", texto).upper() if texto else None
