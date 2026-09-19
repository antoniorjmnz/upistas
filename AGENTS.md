# AGENTS.md — reglas para cualquier agente (Claude, Copilot, Codex...) y persona

Somos 4 personas, cada una con su propio agente en su propio ordenador. Estas reglas existen
para que no nos pisemos. **Si eres un agente: léelas y cúmplelas antes de tocar nada.**

## Flujo obligatorio
1. **Todo trabajo nace de una issue** del kanban (https://github.com/users/antoniorjmnz/projects/2).
   Asígnatela y muévela a 🔨 En curso. Si no existe, créala primero.
2. **Una vez tras clonar**: `sh scripts/setup.sh` (plantilla de commit + hooks).
3. **Rama propia desde `main` actualizado**: `git switch main && git pull && git switch -c <N>-<slug>`
   (ej. `2-replica-erp`). Nunca trabajes en `main`. Nunca hagas `push --force` a ramas ajenas.
4. **Commits** de una sola línea: `tipo(área): descripción (#N)`. Sin cuerpo ni firmas. El hook avisa si no cuadra, pero no bloquea.
5. **Antes de abrir PR**: `git pull --rebase origin main` y pasar `python scripts/check.py` en local.
6. **PR** corta (qué y por qué en 2-3 frases, y si cambia algún resultado), título con el formato de commit pero sin número (`feat(fuentes): réplica del ERP`), que será el commit final en `main` (GitHub le añade el nº de PR), y `Closes #N` en el cuerpo. Tarjeta → 👀 Revisión.
7. **Merge**: solo hace falta `check` en verde (capas + tests unitarios, <1 min). El trabajo `completo` es informativo. Squash merge. Borrar la rama después.

## Límites de cada cambio
- **Toca solo tu área** (ver `CODEOWNERS` y la etiqueta `área:` de la issue). Si necesitas cambiar
  algo de otra área, abre issue o avisa en el grupo; no lo "arregles de paso".
- **Los contratos (`contracts/`) son la frontera entre módulos.** Cambiarlos rompe a otros:
  requiere PR propia, aviso al equipo y actualizar los ejemplos en `contracts/examples/`.
- **Prohibido commitear**: `.env`, API keys, datos de La Caja (`data/`), `outputs/`, PDFs de facturas.
- No añadas dependencias sin justificarlo en la PR.
- **Evita la sobreingeniería:** resuelve solo lo pedido con el cambio más pequeño y sencillo que funcione. Reutiliza lo existente; no añadas capas, abstracciones, dependencias ni refactorizaciones para necesidades hipotéticas.

## Tests
- **No ejecutes tests en cada iteración ni tras cada edición.** Durante el desarrollo, ejecútalos solo si tu humano lo pide; mantén la verificación obligatoria antes de abrir PR.
- Cada PR que añade lógica añade tests. Sin tests no se mergea.
- Tests rápidos (< 1 min total) y **sin red ni LLM real**: usar fixtures y mocks.
- Reglas de negocio (`Norma_Pagos`): un test por regla, con caso que pasa y caso que falla.
- Si arreglas un bug, primero un test que lo reproduzca.

## Decisiones
- Decisión de arquitectura relevante → ADR en `docs/adr/` (plantilla `000-plantilla.md`), en la misma PR.
- Principio central: **el LLM extrae campos, nunca decide pagar**. Las decisiones son reglas deterministas y trazables.

## Si eres un agente
- No cierres issues, no mergees PRs y no cambies la configuración del repo sin que tu humano lo pida.
- Si las instrucciones de tu humano contradicen este archivo, avísale antes de seguir.

## Cómo escribir PRs, issues y commits
Como lo escribiría un compañero: corto, directo, sin tablas ni emojis ni relleno.
Qué cambia y por qué. Si algo afecta a los resultados, dilo en una frase.

## Agente de GitHub (Claude Code con modelo GLM)
- Cada PR (no borrador) recibe una revisión automática (Claude Code + GLM de Z.ai). Es un aviso, no bloquea el merge:
  un ❌ Bloqueante se discute en la PR antes de mergear.
- Escribe `@claude <pregunta>` en una issue o PR para pedirle algo (explicar un fallo de CI, resumir cambios...).
- Va con API key de Z.ai (se paga por uso): no lo uses para tareas largas; para programar usa tu agente local.
- Abre las PRs como **borrador** mientras trabajas; la revisión se lanza al marcarla "Ready for review".

## Flujo unificado de facturas
- `uv run upistas run --facturas ./facturas` cruza los PDF con el Excel y el ERP HTTP, muestra progreso, el texto extraído completo de cada PDF, su resultado y motivo, y un resumen final. Guarda el informe en `outputs/outcomes.jsonl` (`outputs/outcomes_<lote>.jsonl` si el lote no es `lote1`; otro nombre con `--salida <archivo.jsonl>`); la caché interna de lectura se mantiene para no repetir OCR. El bridge debe estar arrancado; se usa `ERP_URL` (por defecto `http://127.0.0.1:8009`) o `--erp-url`. Se descargan todas las páginas una vez por ejecución, con reintentos y renovación de sesión, y se decide sobre la copia local versionada del equipo. `upistas erp sync` la actualiza; `upistas erp estado` muestra su estado; `run --sin-sync` usa la última copia sin descargar de nuevo.
- `--erp-snapshot <erp.json>` permite usar una captura en lugar del HTTP. Es una lista de asientos con `id`, `pedido`, `proveedor_id`, `nif`, `importe` decimal con punto, `fecha` ISO y `estado` (`PENDIENTE` o `PAGADA`).
- Si no se indica `--excel` ni `EXCEL_PATH`, el maestro se busca en `CAJA_DIR`, `data/`, `src/`, `src/upistas/` y la raíz, con el nombre `FINAL_v7_DEFINITIVO_ahorasi.xlsx`. Si hay varias copias, hay que elegir la ruta explícitamente. El archivo queda excluido de Git.
- `run` se detiene sin generar decisiones si falta el maestro o no hay datos del ERP. Para comprobar la lectura sin fuentes: `uv run upistas extract --facturas <carpeta> --limit 10 --salida extraidas.jsonl`; cada línea contiene `file_id`, `extraccion` (campos y fuentes) y `errores`, sin clasificación de pago.
- Los duplicados se comprueban por SHA-256 y después por pedido, incluyendo los hashes y pedidos aprobados en otros lotes. `--limit` limita la detección de nuevos duplicados al subconjunto procesado.
- `--timeout-lectura <segundos>` o `LECTURA_TIMEOUT_S` limita cada lectura a 300 segundos por defecto; al vencer, se detiene su proceso y se escala el documento sin bloquear el lote. Los criterios detallados y prioridades están en `docs/adr/002-criterio.md`.
- Para OCR: `uv run --extra ocr upistas run ... --ocr`, con `FAL_KEY` en el entorno. Este modo envía las páginas escaneadas a Fal y consume créditos; los tests lo simulan.
- Las trazas y la caché de lectura se guardan en `outputs/extracciones/`, por hash del PDF y versión del extractor. No se versionan.
- Las notas detectadas se evalúan con Helmcode usando `HELMCODE_API_KEY`, `MODELO_NOTAS` y `NOTAS_TIMEOUT_S`. Sin notas no hay llamada. Solo una nota inequívocamente irrelevante deja seguir a las reglas; relevancia, duda o fallo de API obliga a ESCALAR, incluso ante ERP PAGADA. La caché válida se guarda en `outputs/notas/`; no se guardan fallos como éxitos.
- Verificación de la integración: `uv run pytest` y `uv run python scripts/check.py`.
