# upistas — contexto para Claude

Hackathon Maisa "500 Sombras de Alberto". Equipo de 4. Ver README.md para reto, calendario y rúbrica.

## Objetivo
Sistema que procesa facturas PDF (nativas y escaneadas), cruza con un Excel caótico de proveedores
y un ERP legado (`http://127.0.0.1:8009`, `make erp` en el repo oficial; ver MANUAL_ERP_2009.md)
y decide `PAGAR` / `NO_PAGAR` / `ESCALAR` por factura.

## Principios (lo que puntúa)
- **Trazabilidad**: cada decisión debe poder seguirse desde el input: qué se extrajo, qué regla aplicó, por qué.
- **Reglas como datos**: la norma cambia (v3.2 → v4 el sábado, dato cambiado el domingo). Cambiar reglas y reprocesar no debe requerir tocar código.
- **Resiliencia**: checkpoint por factura, idempotencia (sin duplicados), reintentos con backoff, fallback si el LLM falla o devuelve algo inválido.
- **Coste**: medir tokens/€ por factura; usar LLM solo donde el determinista no llega.
- **Proporcionado**: mejor pequeño y bien razonado que grande sin criterio.

## Convenciones
- Nunca commitear `.env`, datos del reto ni outputs.
- Toda decisión de arquitectura relevante → nuevo ADR en `docs/adr/` (usar `000-plantilla.md`).
- Salida obligatoria: exactamente un outcome por archivo en `outputs/outcomes.jsonl`.

## Trabajo en equipo
**Lee y cumple [AGENTS.md](AGENTS.md)**: rama por issue, PR con `Closes #N`, `python scripts/check.py`
en verde antes de la PR, no tocar otras áreas ni `contracts/` sin avisar.

## Stack y comandos
Ver [ADR-001](docs/adr/001-stack.md). `uv run pytest` · `uv run upistas run` · `uv run python scripts/check.py`.
- Arquitectura hexagonal: lee [docs/arquitectura.md](docs/arquitectura.md) antes de añadir código.
- Lógica de negocio solo en `dominio/`; los `@DBOS.step` solo orquestan; `contenedor.py` monta los adaptadores.
- `lint-imports` vigila las capas: si falla, el código está en la capa equivocada, no se desactiva.
- Tras cambiar `contracts/*.schema.json`: `uv run python scripts/gen_contracts.py`.
