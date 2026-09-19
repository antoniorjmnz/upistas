# 500 sombras de Alberto — Fase 1

Primera capa del pipeline documental:

```text
PDF
└── página por página
    ├── texto nativo útil -> PyMuPDF
    └── sin texto útil -> render PNG -> Fal GOT-OCR2

                         ↓
                   RAW JSON trazable
```

Esta fase NO interpreta todavía proveedor, NIF, PO, IVA o total.
Primero garantizamos que obtenemos texto de todas las páginas de forma fiable.

## Estructura

```text
backend/
├── app/
│   ├── main.py
│   ├── cli/
│   │   └── extract.py
│   └── extraction/
│       ├── schemas.py
│       ├── pdf_reader.py
│       ├── fal_ocr.py
│       └── pipeline.py
├── data/
│   └── invoices/
├── tests/
├── .env.example
├── requirements.txt
└── Dockerfile
```

## Windows / PowerShell

Desde la raíz del repo:

```powershell
cd backend

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

Copy-Item .env.example .env
```

Edita `.env`:

```env
FAL_KEY=tu_clave_real
```

Copia una factura a:

```text
backend\data\invoices\scan_002.pdf
```

### 1. Probar solo el router (NO llama a Fal)

```powershell
python -m app.cli.route data/invoices/scan_002.pdf
```

Para `scan_002.pdf` debería salir:

```text
page=1 route=fal_ocr image=tmp\pages\...
```

### 2. Ejecutar OCR completo

```powershell
python -m app.cli.extract data/invoices/scan_002.pdf
```

Esto sí llama a Fal si la página no tiene texto nativo.

### 3. API

```powershell
uvicorn app.main:app --reload
```

Abrir:

```text
http://127.0.0.1:8000/docs
```

Usar:

```text
POST /api/extract/raw
```

### 4. Tests

```powershell
pytest -q
```

Los tests no consumen créditos de Fal.

## Resultado esperado

```json
{
  "schema_version": "raw-1.0",
  "document": {
    "filename": "scan_002.pdf",
    "sha256": "...",
    "page_count": 1
  },
  "pages": [
    {
      "page": 1,
      "route": "fal_ocr",
      "text": "...",
      "text_chars": 500,
      "latency_ms": 900,
      "model": "fal-ai/got-ocr/v2",
      "error": null
    }
  ],
  "status": "success"
}
```

Este objeto será la entrada de la Fase 2, donde convertiremos el texto a:

```text
supplier
tax_id
iban
invoice_number
date
PO
subtotal
VAT
total
```
