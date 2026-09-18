# AGENTS.md — reglas para cualquier agente (Claude, Copilot, Codex...) y persona

Somos 4 personas, cada una con su propio agente en su propio ordenador. Estas reglas existen
para que no nos pisemos. **Si eres un agente: léelas y cúmplelas antes de tocar nada.**

## Flujo obligatorio
1. **Todo trabajo nace de una issue** del kanban (https://github.com/users/antoniorjmnz/projects/2).
   Asígnatela y muévela a 🔨 En curso. Si no existe, créala primero.
2. **Una vez tras clonar**: `sh scripts/setup.sh` (plantilla de commit + hooks).
3. **Rama propia desde `main` actualizado**: `git switch main && git pull && git switch -c <N>-<slug>`
   (ej. `2-replica-erp`). Nunca trabajes en `main`. Nunca hagas `push --force` a ramas ajenas.
4. **Commits** con formato `tipo(área): descripción (#N)` (ver `.gitmessage`; el hook lo valida). Los agentes también: usa `git commit -m "..."` con ese formato.
5. **Antes de abrir PR**: `git pull --rebase origin main` y pasar `python scripts/check.py` en local.
6. **PR** con la plantilla (rellena la tabla de Trazabilidad), título `#N: descripción` y `Closes #N` en el cuerpo. Tarjeta → 👀 Revisión.
7. **Merge**: solo con CI en verde. Squash merge. Borrar la rama después.

## Límites de cada cambio
- **Toca solo tu área** (ver `CODEOWNERS` y la etiqueta `área:` de la issue). Si necesitas cambiar
  algo de otra área, abre issue o avisa en el grupo; no lo "arregles de paso".
- **Los contratos (`contracts/`) son la frontera entre módulos.** Cambiarlos rompe a otros:
  requiere PR propia, aviso al equipo y actualizar los ejemplos en `contracts/examples/`.
- **Prohibido commitear**: `.env`, API keys, datos de La Caja (`data/`), `outputs/`, PDFs de facturas.
- No añadas dependencias sin justificarlo en la PR.

## Tests
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
