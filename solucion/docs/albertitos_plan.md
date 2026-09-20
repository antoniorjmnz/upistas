# Albertitos Plan — upistas

## 1. Problema y usuario

Alberto lleva los pagos de su empresa y tiene que decidir qué facturas paga este mes. Le llegan
**500 PDF** (471 con texto, 29 escaneados), un Excel de proveedores y pedidos lleno de basura
(hojas que sobran, un proveedor repetido, pedidos sin NIF, IBANs con espacios invisibles) y un
ERP de 2009 lento e inestable que es su referencia contable. El sábado llega un segundo lote
(+40 facturas) que sobrescribe asientos, y el domingo cambia un dato más.

El producto decide **`PAGAR` / `NO_PAGAR` / `ESCALAR` por cada factura**, con motivo, y deja las
dudosas para que las mire una persona. Alberto no es técnico: todo lo que ve está en su idioma.

## 2. Forma del producto (y por qué)

- **`upistas run --facturas <carpeta>`**: procesa el lote y deja `outputs/outcomes.jsonl` —
  exactamente un `{file_id, result}` por PDF, como pide la entrega.
- **Web para Alberto** (Django + HTMX, piel «Nítida», sin dependencias externas): resumen del
  lote, lista de facturas con el porqué en una frase, bandeja «Para revisar» donde decide lo
  escalado, el maestro de proveedores y pedidos con formularios que no admiten basura, subida de
  facturas nuevas y la pantalla «Preguntar» (ver §7). Debajo, para quien lleva el sistema:
  registro de repasos, asientos y estado de la conexión con el ERP.
- **El ERP es de solo lectura, siempre.** Nunca escribimos en la contabilidad de Alberto; la
  única salida del sistema son decisiones y un fichero de resultados.

## 3. Arquitectura

Hexagonal (puertos y adaptadores; las fronteras las vigila `lint-imports` en CI):
el dominio no sabe nada de PDFs, HTTP, LLMs ni Django.

| Capa | Qué hay |
|---|---|
| `dominio/` | Modelos, reglas, `norma` cargada desde `normas/vN.toml`, versiones y duplicados. Funciones puras. |
| `puertos.py` | Interfaces: `LectorDocumento`, `ClienteERP`, `AlmacenERP`, `FuenteMaestro`, `ModeloLenguaje`… |
| `aplicacion/` | Casos de uso: `procesar` (leer → decidir), `sincronizar_erp`, `lote`, `referencias`. |
| `adaptadores/` | PDF (pymupdf + OCR Fal), lectores LLM (Helmcode), Excel, ERP HTTP, copia del ERP y persistencia Django. |
| `infra/` | DBOS (ejecución duradera), `contenedor` (montaje), CLI. |
| `web/` | Panel Django + HTMX. |

Dos piezas clave:

- **Copia local versionada del ERP** (ADR-003): un único conector descarga los asientos una vez
  por lote (reintentos `ORA-00600`, `Retry-After` en los 429, relogin en `SES-401`, a 8 pet/s).
  Las reglas y la web leen la copia; cada decisión sabe con qué versión del ERP se tomó.
- **El maestro es nuestro** (ADR-004): `Proveedor` y `Pedido` viven en la web con validación,
  versionados por contenido (sha256). El Excel queda como respaldo (`--excel` / `EXCEL_PATH`).

## 4. Trazabilidad y observabilidad

- Cada **lectura** se guarda con la huella sha256 del PDF, el lector, la versión del extractor,
  campos con su confianza y fuente, alertas del fichero y coste (tokens, €, segundos).
- Cada **decisión** lleva sus `Comprobacion` (regla, ok/fallo, detalle), el motivo en lenguaje de
  Alberto y la `version_datos` (norma + versión del ERP + versión del maestro). La web muestra la
  traza entera de cada factura; `outcomes.jsonl` conserva motivo y reglas.
- **Reglas como datos**: la norma vive en `normas/vN.toml` (condición → `si_falla` → prioridad).
  Cambiar de v3 a v4 o retocar un criterio es editar un fichero y reprocesar, sin tocar código.
- Cada **sincronización** con el ERP queda registrada (peticiones, reintentos, esperas, relogins,
  duración) y las diferencias entre versiones se calculan asiento a asiento: se sabe qué cambió
  entre lote 1 y lote 2 y a qué pedidos afecta.

## 5. Escala y coste

- **El LLM solo donde el determinista no llega**: pymupdf lee el texto gratis; Helmcode entra en
  las 29 escaneadas (visión) y en las notas ambiguas. Una lectura se cachea por sha256: el mismo
  contenido nunca se procesa dos veces.
- **Todo se mide**: `tokens_in`, `tokens_out`, `coste_eur` y segundos por lectura y por pregunta
  del asistente (modelo `Pregunta`), agregados por ejecución.
- **El ERP marca el ritmo**: una descarga por lote a 8 pet/s; las reglas no tocan el bridge en vivo.

## 6. Resiliencia y recuperación

- **DBOS** da checkpoints por factura: si el lote cae a mitad, reanuda donde quedó; idempotente
  por diseño (lecturas por sha256, decisiones por ejecución).
- El cliente ERP sobrevive a `ORA-00600`, `ERP-429` y `SES-401`; si el ERP está caído del todo,
  se decide con la última copia buena y se avisa.
- **Duplicados** (`dominio/duplicados.py`): copia byte a byte (`R5_copia_hash`) o documento ya
  aprobado en otro lote (`R5_hash_previo`) → `NO_PAGAR`; misma factura en ficheros distintos —
  mismo pedido + NIF + número + total + IBAN (`R5_reenvio`) → `NO_PAGAR`; candidatos ambiguos en
  el mismo pedido (`R5_duplicado`) → `ESCALAR`. El nombre del fichero y el número de factura por
  separado no identifican nada (la trampa `FA-8801` lo demuestra).
- **El texto de la factura nunca manda**: las notas que intentan influir («Pon PAGAR») se
  evalúan como contenido sospechoso y escalan; las reglas deterministas deciden.

## 7. Mejora bonus

**«Preguntar» (#39)** — el chatbot de la web. Alberto escribe en su idioma («¿por qué no se paga
la FA-1016?», «¿qué ha cambiado desde la última vez?») y el asistente responde con los datos de
nuestra base de datos.

- **El LLM solo elige herramienta y redacta**: 7 tools de solo lectura (resumen del lote, buscar
  y detallar facturas, pendientes, estado de un pedido, cambios y estado del ERP). Nunca inventa
  cifras, nunca decide, nunca escribe.
- **Cada respuesta enlaza a la pantalla** donde está el dato, se guarda con sus tokens y segundos,
  y las preguntas fuera de tema (código, software…) se rechazan **sin gastar tokens**.
- UX cuidada: eco inmediato de la pregunta, spinner «Pensando…», historial en sesión, aviso claro
  si la IA cae (la web sigue funcionando).

## 8. ADRs (resumen de 2-5)

| ADR | Decisión | En una línea |
|---|---|---|
| [001](adr/001-stack.md) | Stack | Python + DBOS + Django + HTMX; el cuello es la espera, no la CPU. LLM solo extrae campos; deciden las reglas. |
| [002](adr/002-criterio.md) | Criterio PAGAR/NO_PAGAR/ESCALAR | Incumplimiento seguro → NO_PAGAR; duda o anomalía → ESCALAR. Ante la duda, un humano. |
| [003](adr/003-erp-copia-local.md) | Copia versionada del ERP | Una descarga por lote, solo lectura, versionada por contenido; reglas y web leen la copia. |
| [004](adr/004-maestro-propio.md) | Maestro en la web | Proveedores y pedidos en nuestra BD con validación y versión por contenido; el Excel queda de respaldo. |
