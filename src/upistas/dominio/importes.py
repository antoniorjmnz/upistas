"""Importes y fechas tal como vienen en facturas, Excel y ERP."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    # Inglés
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    # Portugués
    "janeiro": 1, "fevereiro": 2, "marco": 3, "maio": 5, "junho": 6, "julho": 7,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    # Francés
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    # Italiano
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "settembre": 9, "ottobre": 10, "dicembre": 12,
    # Alemán
    "januar": 1, "februar": 2, "marz": 3, "juni": 6, "juli": 7, "oktober": 10, "dezember": 12,
    # Catalán
    "gener": 1, "febrer": 2, "marc": 3, "maig": 5, "juny": 6, "juliol": 7,
    "agost": 8, "desembre": 12,
}

# Palabras que son un número (1-31 para el día, más lo que hace falta para el año 2000-2099).
_PALABRA_NUM = {
    # Español
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18,
    "diecinueve": 19, "veinte": 20, "veintiuno": 21, "veintiun": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
    "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
    # Inglés (cardinales y ordinales)
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
    # Francés
    "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
    "dixsept": 17, "dixhuit": 18, "dixneuf": 19, "vingt": 20, "trente": 30, "quarante": 40,
    "cinquante": 50, "soixante": 60, "premier": 1, "premiere": 1,
    # Italiano
    "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sette": 7, "otto": 8, "nove": 9,
    "dieci": 10, "undici": 11, "dodici": 12, "tredici": 13, "quattordici": 14, "quindici": 15,
    "sedici": 16, "diciassette": 17, "diciotto": 18, "diciannove": 19, "venti": 20,
    "quaranta": 40, "sessanta": 60, "settanta": 70, "ottanta": 80, "novanta": 90,
    # Alemán (cardinales y ordinales -ten/-sten)
    "eins": 1, "ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "zehn": 10, "elf": 11, "zwolf": 12, "dreizehn": 13,
    "vierzehn": 14, "funfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18,
    "neunzehn": 19, "zwanzig": 20, "dreissig": 30, "vierzig": 40, "funfzig": 50,
    "sechzig": 60, "siebzig": 70, "achtzig": 80, "neunzig": 90,
    "ersten": 1, "erster": 1, "erste": 1, "zweiten": 2, "dritten": 3, "vierten": 4,
    "funften": 5, "sechsten": 6, "siebten": 7, "achten": 8, "neunten": 9, "zehnten": 10,
    "elften": 11, "zwolften": 12, "dreizehnten": 13, "vierzehnten": 14, "funfzehnten": 15,
    "sechzehnten": 16, "siebzehnten": 17, "achtzehnten": 18, "neunzehnten": 19,
    "zwanzigsten": 20, "dreissigsten": 30,
    # Catalán
    "u": 1, "dues": 2, "sis": 6, "set": 7, "vuit": 8, "nou": 9, "deu": 10, "dotze": 12,
    "tretze": 13, "catorze": 14, "setze": 16, "disset": 17, "divuit": 18, "dinou": 19,
    "vint": 20, "trenta": 30,
    # Portugués
    "um": 1, "dois": 2, "quatro": 4, "sete": 7, "oito": 8, "dez": 10, "treze": 13,
    "dezasseis": 16, "dezassete": 17, "dezoito": 18, "dezanove": 19, "vinte": 20, "trinta": 30,
    "noventa": 90,
}

_UNIDADES_DE = {"ein": 1, "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5,
                "sechs": 6, "sieb": 7, "sieben": 7, "acht": 8, "neun": 9}
_UNIDADES_IT = {"un": 1, "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
                "sette": 7, "otto": 8, "nove": 9}
_MILES = {"mil", "mille", "thousand", "mila", "tausend"}
_CONECTORES = {"de", "del", "of", "the", "le", "la", "el", "am", "an", "den", "dem", "vom",
               "im", "lo", "da", "di", "d", "du", "des", "em", "dia", "dies", "tag", "en", "a"}


def _palabra_numero(palabra: str) -> int | None:
    """'veintiséis' | 'twentysix' | 'sechsundzwanzig' | 'duemilaventisei'… → número, o None."""
    if not palabra:
        return None
    if palabra in _PALABRA_NUM:
        return _PALABRA_NUM[palabra]
    if palabra.isdigit():
        return int(palabra)
    # Alemán: sechsundzwanzig = 6 + 20; einundzwanzigsten = 21
    if m := re.fullmatch(r"(ein|eins|zwei|drei|vier|funf|sechs|sieb(?:en)?|acht|neun)und"
                         r"(zwanzig|dreissig|vierzig|funfzig|sechzig|siebzig|achtzig|neunzig)(?:sten?|ten)?", palabra):
        return _UNIDADES_DE[m[1]] + _PALABRA_NUM[m[2]]
    # Alemán: zweitausendsechsundzwanzig = 2000 + 26
    if m := re.fullmatch(r"(ein|eins|zwei|drei|vier|funf|sechs|sieben?|acht|neun)tausend(.*)", palabra):
        resto = _palabra_numero(m[2]) if m[2] else 0
        return _UNIDADES_DE[m[1]] * 1000 + resto if resto is not None else None
    # Italiano: duemilaventisei = 2000 + 26
    if m := re.fullmatch(r"(due|tre|quattro|cinque|sei|sette|otto|nove)mila(.*)", palabra):
        resto = _palabra_numero(m[2]) if m[2] else 0
        return _PALABRA_NUM[m[1]] * 1000 + resto if resto is not None else None
    if m := re.fullmatch(r"(venti|trenta|quaranta|cinquanta|sessanta|settanta|ottanta|novanta)"
                         r"(uno|due|tre|quattro|cinque|sei|sette|otto|nove)", palabra):
        return _PALABRA_NUM[m[1]] + _UNIDADES_IT[m[2]]
    return None


def _numero_texto(tokens: list[str]) -> int | None:
    """'dos mil veintiséis' | 'two thousand twenty six' | 'deux mille vingt six' → número, o None."""
    if not tokens:
        return None
    total = actual = 0
    for tok in tokens:
        if tok in ("y", "e", "i", "et", "and", "und"):
            continue
        if tok in _MILES:
            actual = (actual or 1) * 1000
            continue
        if m := re.fullmatch(r"(.+)tausend", tok):  # alemán compuesto: zweitausend…
            parte = _palabra_numero(tok)
            if parte is None:
                return None
            actual += parte
            continue
        numero = _palabra_numero(tok)
        if numero is None:
            return None
        actual += numero
    return total + actual if actual else None


def parse_fecha_letras(texto: str) -> date | None:
    """Fechas escritas en letra: 'dos de enero de dos mil veintiséis',
    'the seventh of March, two thousand twenty-six', 'am siebten März zweitausendsechsundzwanzig'…"""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    tokens = [p for p in re.split(r"[^a-z0-9]+", t.lower()) if p]
    mes_idx = next((i for i, tok in enumerate(tokens) if tok in MESES), None)
    if mes_idx is None:
        return None
    antes = [w for w in tokens[:mes_idx] if w not in _CONECTORES]
    despues = [w for w in tokens[mes_idx + 1:] if w not in _CONECTORES]
    dia, anyo = _numero_texto(antes), _numero_texto(despues)
    if (dia is None or not 1 <= dia <= 31) and despues:  # 'March 7, 2026': día tras el mes
        dia, anyo = _numero_texto(despues[:1]), _numero_texto(despues[1:])
    try:
        if dia and anyo and 1900 <= anyo <= 2100 and 1 <= dia <= 31:
            return date(anyo, MESES[tokens[mes_idx]], dia)
    except ValueError:
        return None
    return None


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
    """'08/01/2026' | '2026-01-08' | '15 de enero de 2026' | '03 Feb 2026' → date. None si no es válida."""
    t = (texto or "").strip().lower()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    try:
        if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", t):
            return date(int(m[3]), int(m[2]), int(m[1]))
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2}) de ([a-z]+) de (\d{4})", t) or \
                re.fullmatch(r"(\d{1,2}) ([a-z]+) (\d{4})", t):
            if m[2] in MESES:
                return date(int(m[3]), MESES[m[2]], int(m[1]))
    except ValueError:
        return None
    return None


def normaliza_iban(texto: str | None) -> str | None:
    return re.sub(r"[\s.\-\u200b\ufeff]", "", texto).upper() if texto else None
