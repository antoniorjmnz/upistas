# upistas

**¿Nuevo en el proyecto? Empieza por [docs/contexto.md](docs/contexto.md).**
Tablero: https://github.com/users/antoniorjmnz/projects/2

Repo de trabajo del equipo para el hackathon Maisa **"500 Sombras de Alberto"** (ETSIT UPM, 18-20 sep 2026).

> ⚠️ Este repo es **privado**. La entrega va en un repo público aparte que solo contiene
> `outcomes.jsonl`, `outcomes_lote2.jsonl` y `albertitos_plan.pdf`.

## El reto
Procesar facturas PDF (algunas escaneadas) + Excel de proveedores + ERP de 2009 y decidir
para cada factura: `PAGAR`, `NO_PAGAR` o `ESCALAR`.

- Repo oficial (Caja, ERP, manual): https://github.com/ikurotime/500-sombras-de-alberto
- Formato de salida: `{"file_id":"nombre.pdf","result":"PAGAR"}` (una línea por factura)

## Calendario
| Cuándo | Qué |
|---|---|
| Vie 18 · 21:00 | Enunciado + Caja v3.2 |
| Sáb 19 · 18:00 | Lote 2 (+40), actualización ERP, norma v4 |
| Dom 20 | Escenario sorpresa: cambia un dato de la Caja |
| Dom 20 · 10:30 | **Cierre de entrega** |
| Dom 20 | Defensa 10 min |

## Rúbrica
| Criterio | Pts |
|---|---|
| Producto, arquitectura y ADRs | 35 |
| Escalabilidad y coste | 25 |
| Trazabilidad y observabilidad | 20 |
| Resiliencia y recuperación | 10 |
| Calidad de ejecución | 10 |
| Bonus: mejora extra | +10 |

Desempate: escalabilidad → resiliencia → bonus.

## Stack
Python 3.12 · **DBOS** (pipeline duradero) · **Django** + HTMX + Alpine + Tailwind/DaisyUI ·
Helmcode (LLM) · pymupdf · openpyxl. Motivos y alternativas en [ADR-001](docs/adr/001-stack.md).

## Arrancar
```bash
git clone https://github.com/ikurotime/500-sombras-de-alberto ../caja   # datos del reto
cp .env.example .env            # y rellena HELMCODE_API_KEY
sh scripts/setup.sh             # plantilla de commit + hooks
uv sync --extra dev             # instala todo (Python 3.12 incluido)
uv run pytest                   # tests
uv run upistas run --limit 20   # procesa 20 facturas → outputs/outcomes.jsonl
uv run upistas run              # procesa La Caja entera
```
Postgres (opcional, para varios procesos): `docker compose up -d` y `DATABASE_URL` en `.env`.

## Estructura
Arquitectura hexagonal: ver [docs/arquitectura.md](docs/arquitectura.md), con recetas para añadir reglas, normas, lectores o fuentes.
```
src/upistas/
  dominio/        # modelos, reglas y norma: lógica pura, sin E/S
  puertos.py      # interfaces que implementan los adaptadores
  aplicacion/     # casos de uso (leer → decidir)
  adaptadores/    # PDF, Excel, ERP, LLM...
  infra/          # DBOS, montaje de adaptadores, CLI
  contracts/      # modelos GENERADOS desde contracts/ (no editar)
normas/           # la norma de pagos como datos (v3.toml, v4.toml...)
web/              # Django: panel y bandeja de revisión
contracts/        # JSON Schema entre módulos
tests/unit/       # dominio, milisegundos
tests/integracion/# pipeline con DBOS
```
