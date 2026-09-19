"""
Auditoría de facturas PDF contra el Excel FINAL_v7_DEFINITIVO_ahorasi.xlsx

Pestañas usadas:
  Proveedores : ID, Razon Social, NIF, IBAN, CIUDAD, Condiciones
  Pedidos_2026: Pedidos, ProveedorID, Importe_Total, Estado, Fecha_Pedido

Normas (v3): 1 NIF+IBAN en maestro | 2 pedido existe, es del proveedor e importe
igual | 3 IVA y total bien calculados | 4 fecha válida y no futura |
5 estado PENDIENTE y nunca pagar dos veces | 6 ante la duda, ESCALAR.

Uso:
  python auditoria_facturas.py        # procesa todos los PDFs
  python auditoria_facturas.py 10      # prueba solo con los 10 primeros

Requisitos: pip install pandas openpyxl pdfplumber fal-client python-dotenv
Necesita FAL_KEY en el archivo .env para el OCR de los PDFs escaneados.
"""

import datetime
import os
import re
import sys
from collections import defaultdict

import fal_client
import pandas as pd
import pdfplumber
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURACIÓN
# ============================================================
CARPETA_PDFS = "./facturas"
CARPETA_TEXTOS = "./textos_extraidos"   # caché: evita pagar OCR dos veces
EXCEL_UNICO = "FINAL_v7_DEFINITIVO_ahorasi.xlsx"
PESTANA_MAESTRO = "Proveedores"
PESTANA_ERP = "Pedidos_2026"
REPORTE_FINAL = "reporte_auditoria_hackathon.csv"
# Modo prueba: solo se procesan los N primeros PDFs (orden alfabético).
# Pon None para procesar todos. También se puede pasar por consola: python auditoria_facturas.py 20
LIMITE_PRUEBA = 10

TOLERANCIA = 0.01                 # norma 2 y 3
TIPOS_IVA = (21.0, 10.0, 4.0)     # tipos aceptados si la factura no indica el %
MIN_CARACTERES_TEXTO = 30         # menos que esto en una página => se hace OCR
DPI_OCR = 200
# Norma 5 dice "PENDIENTE", pero el ERP (Pedidos_2026) usa "ABIERTO" para todo.
# Se aceptan ambos como "pendiente de pago"; quita ABIERTO si quieres ser literal.
ESTADOS_PAGABLES = {"PENDIENTE", "ABIERTO"}
# Número de pedido: PO-2026-0096. Tolerante a espacios/guiones y a O<->0 del OCR.
PATRON_PEDIDO = r"P[O0]\s?-?\s?2[O0]26\s?-?\s?[O0-9]{3,5}"

# Confusiones típicas del OCR en posiciones que deberían ser dígitos
OCR_DIGITOS = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6"})


# ============================================================
# UTILIDADES
# ============================================================
def norm_id(valor):
    """Solo letras y números en mayúsculas (para NIF, IBAN...)."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(valor).upper())


def id_txt(valor):
    """ID como texto limpio ('1', '1.0' y ' 1 ' -> '1')."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    s = str(valor).strip().upper()
    return re.sub(r"\.0+$", "", s)


def canon_pedido(valor):
    """'PO-2026-0096', 'P0 2026 O096' -> 'PO20260096'."""
    s = norm_id(valor)
    m = re.match(r"^P[O0]2[O0]26(.*)$", s)
    if not m:
        return s
    return "PO2026" + m.group(1).translate(OCR_DIGITOS)


def canon_nif(valor):
    """NIF español: 1 letra + 7 dígitos + letra/dígito. Corrige O/0, I/1... en los dígitos."""
    s = norm_id(valor)
    if len(s) != 9:
        return s
    return s[0] + s[1:8].translate(OCR_DIGITOS) + s[8]


def canon_iban(valor):
    """IBAN español: ES + 22 dígitos. Corrige confusiones del OCR en los dígitos."""
    s = norm_id(valor)
    if not s.startswith("ES"):
        return s
    return "ES" + s[2:].translate(OCR_DIGITOS)


def a_float(valor):
    """'1.210,00' / '1210.00' / 1210 -> 1210.0 ; None si no se puede."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    s = str(valor).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if "," in s and "." in s:
        # el separador que aparece último es el decimal: 1.210,00 / 1,210.00
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def distinto(a, b):
    return round(abs(a - b), 2) > TOLERANCIA


# ============================================================
# 1. CARGAR EL EXCEL
# ============================================================
def exigir_columnas(df, columnas, hoja):
    faltan = [c for c in columnas if c not in df.columns]
    if faltan:
        raise KeyError(
            f"En la pestaña '{hoja}' faltan las columnas {faltan}. "
            f"Columnas encontradas: {list(df.columns)}"
        )


def cargar_base_datos():
    if not os.path.exists(EXCEL_UNICO):
        raise FileNotFoundError(f"No existe '{EXCEL_UNICO}' en {os.getcwd()}")

    maestro = pd.read_excel(EXCEL_UNICO, sheet_name=PESTANA_MAESTRO, dtype=str)
    pedidos = pd.read_excel(EXCEL_UNICO, sheet_name=PESTANA_ERP, dtype=str)
    for df in (maestro, pedidos):
        df.columns = df.columns.str.strip()
        for c in df.columns:               # 'Ofimática Cieza S.L.  ' -> sin espacios
            df[c] = df[c].str.strip()

    exigir_columnas(maestro, ["ID", "NIF", "IBAN"], PESTANA_MAESTRO)
    exigir_columnas(
        pedidos, ["Pedido", "ProveedorID", "Importe_Total", "Estado"], PESTANA_ERP
    )

    maestro["ID"] = maestro["ID"].map(id_txt)
    maestro["NIF_N"] = maestro["NIF"].map(canon_nif)
    maestro["IBAN_N"] = maestro["IBAN"].map(canon_iban)
    # El maestro trae filas repetidas (P007 dos veces). Si son idénticas se quitan;
    # si el mismo NIF tuviera IBAN distinto se conservan y la norma 1 escalará.
    maestro = maestro.drop_duplicates(subset=["ID", "NIF_N", "IBAN_N"]).reset_index(drop=True)

    pedidos["PEDIDO_N"] = pedidos["Pedido"].map(canon_pedido)
    pedidos["PROV_ID"] = pedidos["ProveedorID"].map(id_txt)
    pedidos["NIF_N"] = pedidos["NIF"].map(canon_nif) if "NIF" in pedidos.columns else ""
    pedidos["IMPORTE"] = pedidos["Importe_Total"].map(a_float)
    pedidos["ESTADO_N"] = pedidos["Estado"].fillna("").astype(str).str.strip().str.upper()
    return maestro, pedidos


# ============================================================
# 2. EXTRAER TEXTO (digital u OCR con Fal.ai)
# ============================================================
def ocr_pagina(pagina):
    """OCR de una página con GOT-OCR v2. Devuelve (texto, error)."""
    ruta = f"temp_{os.getpid()}_{pagina.page_number}.png"
    try:
        pagina.to_image(resolution=DPI_OCR).original.save(ruta, format="PNG")
        url = fal_client.upload_file(ruta)
        res = fal_client.subscribe(
            "fal-ai/got-ocr/v2",
            arguments={"input_image_urls": [url]},
            with_logs=False,
        )
        # OJO: la respuesta viene en 'outputs' (lista), no en 'text'
        texto = "\n".join(res.get("outputs", []))
        if not texto.strip():
            return "", f"OCR sin texto en la página {pagina.page_number}"
        return texto, None
    except Exception as e:
        return "", f"OCR falló en la página {pagina.page_number}: {e}"
    finally:
        if os.path.exists(ruta):
            os.remove(ruta)


def extraer_texto(ruta_pdf):
    """Devuelve (texto, metodo, errores). Usa caché en CARPETA_TEXTOS."""
    cache = os.path.join(
        CARPETA_TEXTOS, os.path.basename(ruta_pdf).rsplit(".", 1)[0] + ".txt"
    )
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            primera, _, resto = f.read().partition("\n")
        return resto, primera.replace("#METODO=", "") + "(caché)", []

    partes, errores, usados = [], [], set()
    with pdfplumber.open(ruta_pdf) as pdf:
        for pagina in pdf.pages:
            try:
                texto = pagina.extract_text() or ""
            except Exception:
                texto = ""
            if len(texto.strip()) >= MIN_CARACTERES_TEXTO:
                usados.add("DIGITAL")
            else:
                texto, error = ocr_pagina(pagina)
                usados.add("OCR")
                if error:
                    errores.append(error)
            partes.append(texto)

    texto_total = "\n".join(partes)
    metodo = "+".join(sorted(usados)) if usados else "SIN_PAGINAS"
    if not errores and texto_total.strip():
        with open(cache, "w", encoding="utf-8") as f:
            f.write(f"#METODO={metodo}\n{texto_total}")
    return texto_total, metodo, errores


# ============================================================
# 3. EXTRAER LOS DATOS DE LA FACTURA
# ============================================================
FECHA = r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}|\d{4}-\d{2}-\d{2})"
NUM = r"(-?\d{1,3}(?:\.\d{3})+,\d{2}|-?\d{1,3}(?:,\d{3})+\.\d{2}|-?\d+,\d{2}|-?\d+\.\d{2})"
PCT = r"(?:\(?\s*\d{1,2}(?:[.,]\d+)?\s*%\s*\)?[^\n\d]*)?"

ETQ_BASE = r"(?:BASE\s+IMPONIBLE|SUBTOTAL|BASE)"
ETQ_IVA = r"\bI\.?V\.?A\b\.?"
ETQ_TOTAL = r"(?<![A-Z])TOTAL(?!\s+(?:IVA|I\.V\.A|IMPUESTOS|BASE))"


def buscar_importe(t, etiqueta, ultimo=False):
    ms = list(re.finditer(etiqueta + r"[^\n\d]*" + PCT + NUM, t))
    if not ms:
        return None
    return a_float((ms[-1] if ultimo else ms[0]).group(1))


def buscar_fecha(t):
    m = re.search(
        r"FECHA(?!\s+(?:DE\s+)?(?:VENC|PAGO|ENTREGA))[^\n\d]{0,30}" + FECHA, t
    ) or re.search(FECHA, t)
    if not m:
        return None, "no se encontró ninguna fecha"
    raw = m.group(1)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw, fmt).date(), None
        except ValueError:
            pass
    return None, f"fecha inválida '{raw}'"


def analizar(texto, maestro):
    t = texto.upper().replace("\u2013", "-").replace("\u2014", "-")
    notas = []

    # NIF: candidatos etiquetados en la factura (NIF/CIF), excluyendo el del cliente
    # (línea 'Cliente: ... CIF: ...'), y además cualquier patrón de NIF suelto.
    etiquetados = [
        canon_nif(m.group(1))
        for m in re.finditer(r"(?:NIF|CIF)[^A-Z0-9]{0,5}([A-Z0-9][A-Z0-9 .\-]{7,11})", t)
        if "CLIENTE" not in t[max(0, m.start() - 40):m.start()]
    ]
    sueltos = [
        canon_nif(x)
        for x in re.findall(r"\b[A-Z][O0-9IL]{7}[A-Z0-9]\b", t)
        if len(re.findall(r"\d", x)) >= 4
    ]
    nifs_factura = set(etiquetados) | set(sueltos)
    # el último carácter puede ser letra o dígito: se prueba también corregido (B->8, O->0)
    nifs_factura |= {n[:8] + n[8:].translate(OCR_DIGITOS) for n in nifs_factura if len(n) == 9}
    provs = maestro[maestro["NIF_N"].isin(nifs_factura)]
    m_nif = etiquetados[0] if etiquetados else None

    # IBAN español (con o sin separadores), tolerante a O/I/S/B en vez de dígitos
    D = r"[0-9OQDILSBZG]"
    ibans = {
        canon_iban(x)
        for x in re.findall(rf"ES{D}{{2}}(?:[\s\-]?{D}{{4}}){{5}}", t)
    }

    # Pedido
    pedidos = {canon_pedido(x) for x in re.findall(PATRON_PEDIDO, t)}

    fecha, error_fecha = buscar_fecha(t)

    # Importes: primero por etiqueta; si falla, últimos tres números coherentes
    base = buscar_importe(t, ETQ_BASE)
    iva = buscar_importe(t, ETQ_IVA)
    total = buscar_importe(t, ETQ_TOTAL, ultimo=True)
    if None in (base, iva, total):
        nums = [a_float(x) for x in re.findall(NUM, t)]
        if len(nums) >= 3 and not distinto(nums[-3] + nums[-2], nums[-1]):
            base, iva, total = nums[-3:]
            notas.append("importes por posición (sin etiquetas)")

    m_tipo = re.search(r"\bI\.?V\.?A\b\.?[^\n\d]*(\d{1,2}(?:[.,]\d+)?)\s*%", t)

    return {
        "proveedores": provs,
        "nif_etiquetado": m_nif,
        "ibans": ibans,
        "pedidos": pedidos,
        "fecha": fecha,
        "error_fecha": error_fecha,
        "base": base,
        "iva": iva,
        "total": total,
        "tipo_iva": a_float(m_tipo.group(1)) if m_tipo else None,
        "notas": notas,
    }


# ============================================================
# 4. EVALUAR LAS NORMAS (devuelve la lista de motivos; vacía = PAGAR)
# ============================================================
def evaluar(d, pedidos, hoy):
    motivos = []
    prov = None

    # ---- Norma 1: NIF en el maestro e IBAN coincidente ----
    provs = d["proveedores"]
    if len(provs) == 0:
        extra = f" (NIF etiquetado en la factura: {d['nif_etiquetado']})" if d["nif_etiquetado"] else ""
        motivos.append(f"N1: ningún NIF del maestro aparece en la factura{extra}")
    elif len(provs) > 1:
        motivos.append(f"N1: aparecen varios proveedores del maestro (NIF {list(provs['NIF'])})")
    else:
        prov = provs.iloc[0]
        iban_m = prov["IBAN_N"]
        if not iban_m:
            motivos.append("N1: el maestro no tiene IBAN para este proveedor")
        elif not d["ibans"]:
            motivos.append("N1: no se encontró ningún IBAN en la factura")
        elif d["ibans"] != {iban_m}:
            motivos.append(f"N1: IBAN de la factura {sorted(d['ibans'])} no coincide con el maestro ({iban_m})")

    # ---- Norma 2 y 5: pedido, titular, importe y estado ----
    codigos = d["pedidos"]
    if not codigos:
        motivos.append("N2: no se encontró número de pedido en la factura")
    elif len(codigos) > 1:
        motivos.append(f"N2: la factura cita varios pedidos {sorted(codigos)}")
    else:
        cod = next(iter(codigos))
        filas = pedidos[pedidos["PEDIDO_N"] == cod]
        if filas.empty:
            motivos.append(f"N2: el pedido {cod} no existe en Pedidos_2026")
        elif len(filas) > 1:
            motivos.append(f"N2: el pedido {cod} aparece {len(filas)} veces en Pedidos_2026")
        else:
            fila = filas.iloc[0]
            if prov is not None and fila["PROV_ID"] != prov["ID"]:
                motivos.append(
                    f"N2: el pedido {cod} pertenece al proveedor ID {fila['PROV_ID']}, "
                    f"no al ID {prov['ID']} de la factura"
                )
            if prov is not None and fila["NIF_N"] and fila["NIF_N"] != prov["NIF_N"]:
                motivos.append(
                    f"N2: el NIF del pedido {cod} en el ERP ({fila['NIF_N']}) no es el del "
                    f"proveedor de la factura ({prov['NIF_N']})"
                )
            if d["total"] is None:
                motivos.append("N2: no se pudo leer el total de la factura para compararlo con el pedido")
            elif fila["IMPORTE"] is None:
                motivos.append(f"N2: el Importe_Total del pedido {cod} no es un número legible")
            elif distinto(d["total"], fila["IMPORTE"]):
                motivos.append(f"N2: total factura {d['total']} EUR != pedido {fila['IMPORTE']} EUR")
            if fila["ESTADO_N"] not in ESTADOS_PAGABLES:
                motivos.append(
                    f"N5: estado del pedido = {fila['ESTADO_N'] or 'VACÍO'} "
                    f"(debe ser {'/'.join(sorted(ESTADOS_PAGABLES))})"
                )

    # ---- Norma 3: IVA y total ----
    base, iva, total = d["base"], d["iva"], d["total"]
    if None in (base, iva, total):
        faltan = [n for n, v in (("base", base), ("IVA", iva), ("total", total)) if v is None]
        motivos.append(f"N3: no se pudo leer {', '.join(faltan)}")
    else:
        candidatos = [d["tipo_iva"]] if d["tipo_iva"] is not None else TIPOS_IVA
        if not any(not distinto(iva, round(base * c / 100, 2)) for c in candidatos):
            motivos.append(f"N3: IVA {iva} no corresponde a la base {base} al tipo {list(candidatos)}%")
        if distinto(total, base + iva):
            motivos.append(f"N3: total {total} != base {base} + IVA {iva}")

    # ---- Norma 4: fecha válida y no futura ----
    if d["fecha"] is None:
        motivos.append(f"N4: {d['error_fecha']}")
    elif d["fecha"] > hoy:
        motivos.append(f"N4: fecha futura ({d['fecha']})")

    return motivos


# ============================================================
# 5. AUDITORÍA COMPLETA
# ============================================================
def main():
    limite = int(sys.argv[1]) if len(sys.argv) > 1 else LIMITE_PRUEBA

    if not os.getenv("FAL_KEY"):
        print("⚠️  No hay FAL_KEY en .env: los PDFs escaneados irán a ESCALAR.")

    maestro, pedidos = cargar_base_datos()
    print(f"📖 Maestro: {len(maestro)} proveedores | Pedidos: {len(pedidos)}")

    if not os.path.isdir(CARPETA_PDFS):
        print(f"⚠️ No existe la carpeta '{CARPETA_PDFS}'")
        return
    os.makedirs(CARPETA_TEXTOS, exist_ok=True)

    archivos = sorted(f for f in os.listdir(CARPETA_PDFS) if f.lower().endswith(".pdf"))
    if limite:
        archivos = archivos[:limite]
    print(f"🚀 {len(archivos)} PDFs a procesar" + (f" (MODO PRUEBA: solo los {limite} primeros)" if limite else ""))

    hoy = datetime.date.today()
    filas = []

    for i, archivo in enumerate(archivos, 1):
        print(f"⏳ [{i}/{len(archivos)}] {archivo}")
        fila = {"Archivo_PDF": archivo}
        try:
            texto, metodo, errores = extraer_texto(os.path.join(CARPETA_PDFS, archivo))
            d = analizar(texto, maestro)
            motivos = [f"LECTURA: {e}" for e in errores]
            if not texto.strip():
                motivos.append("LECTURA: no se pudo extraer texto del PDF")
            motivos += evaluar(d, pedidos, hoy)
            prov = d["proveedores"].iloc[0] if len(d["proveedores"]) == 1 else None
            fila.update({
                "Metodo_Lectura": metodo,
                "Proveedor_ID": prov["ID"] if prov is not None else None,
                "Proveedor": prov.get("Razon Social") if prov is not None else None,
                "NIF_Detectado": prov["NIF"] if prov is not None else d["nif_etiquetado"],
                "IBAN_Detectado": " / ".join(sorted(d["ibans"])) or None,
                "Pedido_Asociado": " / ".join(sorted(d["pedidos"])) or None,
                "Fecha": d["fecha"],
                "Base": d["base"], "IVA": d["iva"], "Importe_Total": d["total"],
                "Notas": " | ".join(d["notas"]) or None,
            })
        except Exception as e:  # cualquier fallo => ESCALAR (norma 6)
            motivos = [f"ERROR PROCESANDO: {e}"]
            fila["Metodo_Lectura"] = "ERROR"
        fila["_motivos"] = motivos
        filas.append(fila)

    # Norma 5: un mismo pedido en varias facturas => se escalan TODAS
    por_pedido = defaultdict(list)
    for f in filas:
        if f.get("Pedido_Asociado") and " / " not in f["Pedido_Asociado"]:
            por_pedido[f["Pedido_Asociado"]].append(f["Archivo_PDF"])
    for f in filas:
        ped = f.get("Pedido_Asociado")
        if ped in por_pedido and len(por_pedido[ped]) > 1:
            otras = [a for a in por_pedido[ped] if a != f["Archivo_PDF"]]
            f["_motivos"].append(f"N5: el pedido {ped} también aparece en {otras}")

    for f in filas:
        motivos = f.pop("_motivos")
        f["Estado_Auditoria"] = "ESCALAR" if motivos else "PAGAR"
        f["Observaciones_Seguridad"] = " | ".join(motivos) or "Todas las normas cumplen"

    df = pd.DataFrame(filas)
    df.to_csv(REPORTE_FINAL, index=False, encoding="utf-8-sig")
    print("\n" + df["Estado_Auditoria"].value_counts().to_string())
    print(f"🎉 Reporte en '{REPORTE_FINAL}' | textos extraídos en '{CARPETA_TEXTOS}'")


if __name__ == "__main__":
    main()