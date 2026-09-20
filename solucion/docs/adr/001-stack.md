# ADR-001: Stack — Python + DBOS + Django + HTMX, LLM en Helmcode

- **Estado**: aceptado
- **Fecha**: 2026-09-19

## Contexto
Alberto necesita decidir PAGAR / NO_PAGAR / ESCALAR para 500 facturas (y un lote 2 el sábado),
cruzando PDFs (29 escaneados), un Excel caótico y un ERP de 2009 lento e inestable
(ORA-00600 aleatorios, ERP-429, sesión de 15 min / 300 usos). Mañana querrá más volumen y
nuevos tipos de archivo, y respuestas aunque un proveedor de modelos falle.

Observación clave: **el cuello de botella es la espera, no la CPU**. Cada factura espera al LLM
(~1–2 s), al ERP y a disco. Un lenguaje "más rápido" no cambia el throughput; lo que lo cambia es
cuánta concurrencia controlada soportamos y qué pasa cuando algo falla a mitad.

## Decisión
| Capa | Elección |
|---|---|
| Pipeline | **DBOS** (ejecución duradera como librería, estado en SQLite/Postgres) |
| Web y back-office | **Django** + **HTMX** + Alpine.js + Tailwind/DaisyUI |
| Extracción | pymupdf (texto) + LLM vía **Helmcode** (API OpenAI; `deepseek-v4-flash` visión con `gemma4` de respaldo, `glm5.3` texto) |
| Datos de referencia | openpyxl (Excel), httpx (ERP) |
| Contratos | JSON Schema → modelos Pydantic generados |

Principio transversal: **el LLM solo extrae campos; las decisiones las toman reglas deterministas**.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| **Celery** (+ Redis) | Reintenta tareas enteras: tras una caída repite la llamada al LLM y al ERP. Checkpoints, idempotencia y trazas por paso habría que programarlos a mano. |
| **Temporal** | Lo mejor del mercado, pero exige operar su servidor y escribir workflows deterministas. Coste de aprendizaje y operación desproporcionado para 36 h. |
| **Rails 8** (Solid Queue) | Muy productivo, pero reintenta jobs completos y el ecosistema PDF de Ruby es más pobre. Nadie del equipo lo domina. |
| **FastAPI + React** | Mejor si hubiera una persona dedicada a front. Dos proyectos, API y build que mantener; no mejora lo que puntúa. |
| **Streamlit** | Rápido para métricas, insuficiente para una bandeja de revisión real. |
| **LLM decide la factura** | No auditable, no reproducible, caro. La norma es 100 % verificable con reglas. |

## Consecuencias
- **Resiliencia**: si el proceso muere, al arrancar se retoma cada factura desde su último paso;
  el ID de workflow `lote:norma:file_id` evita duplicados. Si el LLM falla, la factura afectada
  va a ESCALAR con motivo; el resto no se ve afectado.
- **Escala**: una cola con concurrencia global y rate-limit (respeta ERP y Helmcode). Más
  throughput = más workers apuntando a Postgres; sin cambiar código. SQLite en local, Postgres
  (`docker-compose.yml`) para varios procesos.
- **Trazabilidad**: el historial de pasos de cada factura vive en la base de datos y lo pinta el panel.
- **Coste**: Helmcode es tarifa plana en modelos abiertos → coste marginal por factura ≈ 0 €;
  los modelos frontier solo como respaldo.
- **Riesgo aceptado**: DBOS es joven (≈1,6k★), aunque con 544k descargas/semana y v3.0 del
  16/09/2026. Mitigación: la lógica de negocio no depende de DBOS (funciones puras testeadas).

## Evidencia
- Radar de stacks con métricas de GitHub/npm/PyPI del 18/09/2026 (artifact del equipo).
- Prueba de caída: proceso matado entre `extraer` y `decidir`; al relanzar, la factura terminó
  (PAGAR) con **una sola** llamada a `extraer`.
- Esqueleto: 500 facturas recorridas de punta a punta en 35,7 s con pasos vacíos (SQLite, 1 proceso).
