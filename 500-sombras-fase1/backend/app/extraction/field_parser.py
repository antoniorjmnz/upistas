from __future__ import annotations

import re
from datetime import datetime


# ============================================================
# FIELD HELPERS
# ============================================================

def make_field(
    value,
    raw_value: str | None,
    page: int | None,
    source: str | None,
):
    """
    Campo trazable.

    value:
        valor normalizado que usará el sistema.

    raw_value:
        texto original observado en el documento/OCR.
    """

    return {
        "value": value,
        "raw_value": raw_value,
        "page": page,
        "source": source,
        "confidence": None,
    }


def empty_field():
    return make_field(
        value=None,
        raw_value=None,
        page=None,
        source=None,
    )


# ============================================================
# MONEY NORMALIZATION
# ============================================================

def normalize_ocr_money(
    raw: str,
) -> float | None:
    """
    Normaliza formatos monetarios normales y errores típicos OCR.

    Ejemplos:

        1.564,38  -> 1564.38
        1.564.38  -> 1564.38
        1292.88   -> 1292.88
        1.292.88  -> 1292.88
        1 564,38  -> 1564.38
    """

    if not raw:
        return None

    value = (
        raw
        .upper()
        .replace("EUR", "")
        .replace("€", "")
        .replace("\u00a0", "")
        .replace(" ", "")
        .strip()
    )

    if not value:
        return None

    # --------------------------------------------------------
    # Formato europeo:
    #
    # 1.564,38
    # 1564,38
    # --------------------------------------------------------

    if "," in value:

        # Si existen puntos, se consideran separadores de miles.
        value = (
            value
            .replace(".", "")
            .replace(",", ".")
        )

    else:

        # ----------------------------------------------------
        # Error típico OCR:
        #
        # 1.564.38
        # 1.292.88
        #
        # El último punto actúa como separador decimal.
        # ----------------------------------------------------

        parts = value.split(".")

        if (
            len(parts) > 2
            and len(parts[-1]) == 2
        ):
            value = (
                "".join(parts[:-1])
                + "."
                + parts[-1]
            )

    try:
        return float(value)

    except ValueError:
        return None


# ============================================================
# PURCHASE ORDER
# ============================================================

def extract_purchase_order(
    text: str,
    page: int,
    source: str,
):
    """
    Tolera:

        PO-2026-0478
        PO- 2026-0478
        PO - 2026 - 0478
        P O - 2026 - 0478
    """

    pattern = re.compile(
        r"P\s*O\s*"
        r"-?\s*"
        r"(\d{4})"
        r"\s*-\s*"
        r"(\d+)",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return empty_field()

    value = (
        f"PO-{match.group(1)}-{match.group(2)}"
    )

    return make_field(
        value=value,
        raw_value=match.group(0),
        page=page,
        source=source,
    )


# ============================================================
# INVOICE NUMBER
# ============================================================

def extract_invoice_number(
    text: str,
    page: int,
    source: str,
):
    """
    Tolera OCR del tipo:

        Factura 2026/50749
        Fact ura 2026/50749
        F a c t u r a 2026/50749
    """

    pattern = re.compile(
        r"F\s*a\s*c\s*t\s*u\s*r\s*a"
        r"\s*[:#-]?\s*"
        r"([0-9]{4}\s*/\s*[0-9]+)",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return empty_field()

    value = re.sub(
        r"\s+",
        "",
        match.group(1),
    )

    return make_field(
        value=value,
        raw_value=match.group(0),
        page=page,
        source=source,
    )


# ============================================================
# DATE
# ============================================================

def extract_date(
    text: str,
    page: int,
    source: str,
):
    """
    Observado:

        Fecha 23/07/2026
        Fec ha 23/07/2026

    Normalizado:

        2026-07-23
    """

    pattern = re.compile(
        r"F\s*e\s*c\s*h\s*a"
        r"\s*[:#-]?\s*"
        r"(\d{1,2}/\d{1,2}/\d{4})",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return empty_field()

    raw_date = match.group(1)

    try:
        normalized_date = datetime.strptime(
            raw_date,
            "%d/%m/%Y",
        ).date().isoformat()

    except ValueError:
        normalized_date = None

    return make_field(
        value=normalized_date,
        raw_value=match.group(0),
        page=page,
        source=source,
    )


# ============================================================
# CUSTOMER CIF
# ============================================================

def extract_customer_tax_id(
    text: str,
    page: int,
    source: str,
):
    """
    Tolera:

        CIF A58231074
        C IF A 58231074
        C I F: A 58231074
    """

    pattern = re.compile(
        r"C\s*I\s*F"
        r"\s*:?\s*"
        r"([A-Z])"
        r"\s*"
        r"(\d{8})",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return empty_field()

    value = (
        match.group(1).upper()
        + match.group(2)
    )

    return make_field(
        value=value,
        raw_value=match.group(0),
        page=page,
        source=source,
    )


# ============================================================
# SUBTOTAL / BASE
# ============================================================

def extract_subtotal(
    text: str,
    page: int,
    source: str,
):
    """
    Tolera:

        Base 1.292,88
        Base 1.292.88
        B a s e 1292.88
    """

    pattern = re.compile(
        r"B\s*a\s*s\s*e"
        r"\s*[:#-]?\s*"
        r"([0-9][0-9., ]*[0-9])",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return empty_field()

    raw_number = match.group(1)

    value = normalize_ocr_money(
        raw_number
    )

    return make_field(
        value=value,
        raw_value=match.group(0),
        page=page,
        source=source,
    )


# ============================================================
# IVA %
# ============================================================

def extract_tax_rate(
    text: str,
    page: int,
    source: str,
):
    """
    Tolera:

        IVA 21%
        IV A 21%
        I V A 21 %
    """

    pattern = re.compile(
        r"I\s*V\s*A"
        r"\s*[:#-]?\s*"
        r"([0-9]{1,2}(?:[.,][0-9]+)?)"
        r"\s*%",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return empty_field()

    raw_rate = match.group(1)

    try:
        value = float(
            raw_rate.replace(",", ".")
        )

    except ValueError:
        value = None

    return make_field(
        value=value,
        raw_value=match.group(0),
        page=page,
        source=source,
    )


# ============================================================
# IVA AMOUNT
# ============================================================

def extract_tax_amount(
    text: str,
    page: int,
    source: str,
):
    """
    Ejemplos:

        IVA 21% 271,50
        IV A 21%271.50
    """

    pattern = re.compile(
        r"I\s*V\s*A"
        r"\s*[:#-]?\s*"
        r"[0-9]{1,2}(?:[.,][0-9]+)?"
        r"\s*%"
        r"\s*"
        r"([0-9][0-9., ]*[0-9])",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return empty_field()

    raw_number = match.group(1)

    value = normalize_ocr_money(
        raw_number
    )

    return make_field(
        value=value,
        raw_value=match.group(0),
        page=page,
        source=source,
    )


# ============================================================
# TOTAL
# ============================================================

def extract_total(
    text: str,
    page: int,
    source: str,
):
    """
    Tolera:

        TOTAL 1.564,38 EUR
        TOTAL 1.564.38 EUR
        T O T A L 1564.38
    """

    pattern = re.compile(
        r"T\s*O\s*T\s*A\s*L"
        r"\s*[:#-]?\s*"
        r"([0-9][0-9., ]*[0-9])",
        re.IGNORECASE,
    )

    match = pattern.search(text)

    if not match:
        return empty_field()

    raw_number = match.group(1)

    value = normalize_ocr_money(
        raw_number
    )

    return make_field(
        value=value,
        raw_value=match.group(0),
        page=page,
        source=source,
    )


# ============================================================
# CURRENCY
# ============================================================

def extract_currency(
    text: str,
) -> str | None:

    if re.search(
        r"\bEUR\b",
        text,
        re.IGNORECASE,
    ):
        return "EUR"

    if "€" in text:
        return "EUR"

    return None


# ============================================================
# VALIDATIONS
# ============================================================

def validate_amounts(
    subtotal: float | None,
    tax_amount: float | None,
    total: float | None,
):
    """
    Comprueba:

        subtotal + IVA = total

    Esta validación es determinista.
    """

    if (
        subtotal is None
        or tax_amount is None
        or total is None
    ):
        return {
            "status": "UNKNOWN",
            "reason": "missing_values",
            "expected": None,
            "observed": total,
        }

    expected = round(
        subtotal + tax_amount,
        2,
    )

    observed = round(
        total,
        2,
    )

    difference = round(
        abs(expected - observed),
        2,
    )

    return {
        "status": (
            "PASS"
            if difference <= 0.01
            else "FAIL"
        ),
        "expected": expected,
        "observed": observed,
        "difference": difference,
    }


def validate_tax_calculation(
    subtotal: float | None,
    tax_rate: float | None,
    tax_amount: float | None,
):
    """
    Comprueba:

        subtotal * IVA% = IVA amount
    """

    if (
        subtotal is None
        or tax_rate is None
        or tax_amount is None
    ):
        return {
            "status": "UNKNOWN",
            "reason": "missing_values",
        }

    expected = round(
        subtotal * tax_rate / 100,
        2,
    )

    observed = round(
        tax_amount,
        2,
    )

    difference = round(
        abs(expected - observed),
        2,
    )

    return {
        "status": (
            "PASS"
            if difference <= 0.01
            else "FAIL"
        ),
        "expected": expected,
        "observed": observed,
        "difference": difference,
    }


# ============================================================
# MAIN PARSER
# ============================================================

def parse_pages(
    pages: list[dict],
) -> dict:
    """
    Convierte la salida cruda del OCR en datos estructurados.

    IMPORTANTE:
    Este parser solo devuelve aquello que puede encontrar
    en el documento.

    No consulta ERP.
    No inventa supplier_id.
    No sustituye valores por información externa.
    """

    result = {
        "invoice_number": empty_field(),
        "issue_date": empty_field(),
        "purchase_order": empty_field(),
        "customer_tax_id": empty_field(),

        "subtotal": empty_field(),
        "tax_rate": empty_field(),
        "tax_amount": empty_field(),
        "total": empty_field(),

        "currency": None,

        "validations": {},
    }

    for page_data in pages:

        text = page_data.get(
            "text",
            "",
        )

        if not text:
            continue

        page = page_data.get(
            "page"
        )

        source = (
            page_data.get("route")
            or page_data.get("source")
        )

        candidates = {
            "invoice_number":
                extract_invoice_number(
                    text,
                    page,
                    source,
                ),

            "issue_date":
                extract_date(
                    text,
                    page,
                    source,
                ),

            "purchase_order":
                extract_purchase_order(
                    text,
                    page,
                    source,
                ),

            "customer_tax_id":
                extract_customer_tax_id(
                    text,
                    page,
                    source,
                ),

            "subtotal":
                extract_subtotal(
                    text,
                    page,
                    source,
                ),

            "tax_rate":
                extract_tax_rate(
                    text,
                    page,
                    source,
                ),

            "tax_amount":
                extract_tax_amount(
                    text,
                    page,
                    source,
                ),

            "total":
                extract_total(
                    text,
                    page,
                    source,
                ),
        }

        # Nos quedamos con la primera aparición válida.
        for key, candidate in candidates.items():

            if (
                result[key]["value"] is None
                and candidate["value"] is not None
            ):
                result[key] = candidate

        if result["currency"] is None:

            currency = extract_currency(
                text
            )

            if currency:
                result["currency"] = currency

    # ========================================================
    # VALIDACIONES DETERMINISTAS
    # ========================================================

    result["validations"][
        "subtotal_plus_tax_equals_total"
    ] = validate_amounts(
        subtotal=result["subtotal"]["value"],
        tax_amount=result["tax_amount"]["value"],
        total=result["total"]["value"],
    )

    result["validations"][
        "tax_calculation"
    ] = validate_tax_calculation(
        subtotal=result["subtotal"]["value"],
        tax_rate=result["tax_rate"]["value"],
        tax_amount=result["tax_amount"]["value"],
    )

    return result