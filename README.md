# upistas

📋 **Kanban**: https://github.com/users/antoniorjmnz/projects/2

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

## Estructura
```
data/        # facturas, Excel, lote 2 (no versionado)
outputs/     # outcomes*.jsonl, trazas (no versionado)
docs/adr/    # decisiones de arquitectura (2-5 para el PDF)
docs/albertitos_plan.md  # fuente del PDF de entrega
```

## Setup
```bash
git clone https://github.com/ikurotime/500-sombras-de-alberto ../caja
cp .env.example .env   # y rellena la API key
```
