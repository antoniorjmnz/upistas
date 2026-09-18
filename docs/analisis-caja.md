# Análisis de La Caja (viernes 18, 21:10)

Primera exploración de los datos oficiales antes de decidir arquitectura. Cifras de un parser
de prueba (regex), no definitivas.

## Qué hay

| Fuente | Contenido | Trampas vistas |
|---|---|---|
| `facturas/` | 500 PDF (478 de 1 pág., 22 de 2 págs.) | 29 escaneados sin capa de texto (`scan_*`, `fax_*`, `copia_*`, `reimpresion_*`): texto pequeño y ligeramente rotado |
| Excel `FINAL_v7_DEFINITIVO_ahorasi.xlsx` | 15 hojas; útiles: `Proveedores` (11), `Pedidos_2026` (516), **`Norma_Pagos_v3`** | Proveedor P007 duplicado; espacios sobrantes en razón social; hojas basura (`NO_TOCAR`, `MACROS_ROTAS`...); **17 pedidos cuyo proveedor no coincide con el ERP** (PO-2026-0538..0548...) |
| ERP (`make erp`) | 516 asientos, 26 páginas de 20 | XML ISO-8859-1, fechas DD/MM/AAAA, importes `12.874,40`; `ORA-00600` y `ERP-429` aleatorios; sesión 15 min/300 usos. **9 pedidos ya PAGADA** |

Descarga completa del ERP con reintentos: ~2 s en modo `--rapido` (2×500, 2×429 absorbidos).

## La norma (hoja `Norma_Pagos_v3`)

1. NIF en el maestro **y** IBAN de la factura = IBAN del maestro.
2. Pedido existe, es del proveedor y importe factura = importe pedido (±0,01 €).
3. IVA bien calculado y total = base + IVA (±0,01 €).
4. Fecha válida y no futura.
5. Estado ERP del pedido = `PENDIENTE`. Nunca pagar dos veces el mismo pedido.
6. Anomalía que deba ver un humano → `ESCALAR` con motivo. **Ante duda razonable, escalar antes que pagar.**

Pistas en `notas_alberto`: *"NUNCA pagar sin cruzar con el ERP"*, *"preguntar a Sonia lo del IVA reducido (aplica??)"*.
`pendiente_revisar`: PO-2026-0007, PO-2026-0141.

## Plantillas de factura

Al menos ~10 layouts distintos para el mismo tipo de dato:

- Etiquetas: `Pedido:` / `PO:` / `Ref. Pedido:` / `Su pedido:` / `PEDIDO CLIENTE:` / `Pedido asociado:`
- Totales: `Base:` / `Subtotal:` / `BASE IMPONIBLE....` / `Importe base:`; `IVA (21%)` / `I.V.A. (21%)` / `Cuota IVA (21%)`
- Números: `2.489,99` (ES) y `EUR 1498.30` (EN)
- Fechas: `08/01/2026` y `15 de enero de 2026`
- Idioma mezclado (`Invoice #`, `Bill to`)

Un regex ingenuo falla en ~40% de los PDF con texto → la extracción es el problema difícil.

## Señales detectadas (parser de prueba, parcial)

IBAN distinto: 7 · Pedido PAGADA en ERP: 6 · NIF fuera del maestro: 3 · Pedido inexistente: 3 ·
Pedido de otro proveedor: 2 · IVA mal calculado: 2 · (+ lo que esconden las 196 no parseadas y las 29 escaneadas)

## Implicaciones para el diseño

1. **Las decisiones son deterministas; la extracción no.** La norma es 100% verificable con
   reglas → el LLM solo debe *extraer* campos, nunca *decidir* pagar. Auditable y barato.
2. **Fuente de verdad: ERP > Excel** (el manual lo dice: "referencia contable oficial"). Las
   discrepancias Excel↔ERP son en sí una anomalía → ESCALAR.
3. **Réplica local del ERP**: descargar una vez, con reintentos/backoff/renovación de sesión, y
   trabajar en local. Refrescar al cargar el lote 2.
4. **Extracción en cascada**: texto PDF → parser determinista → LLM de texto si falta/duda →
   LLM con visión para escaneados. Cada campo lleva su método y confianza en la traza.
5. **Validación cruzada de la extracción**: base + IVA = total y suma de líneas = base sirven
   como checksum; si no cuadra tras LLM → ESCALAR, no adivinar.
6. **Reglas como datos versionados** (v3 → v4 el sábado) para reprocesar sin tocar código.
