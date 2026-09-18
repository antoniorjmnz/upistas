---
description: Cerrar el trabajo de la rama actual y abrir la PR
---
Cierra el trabajo de esta rama:

1. `git pull --rebase origin main` y resuelve conflictos si los hay.
2. `uv run python scripts/check.py`. Si algo falla, arréglalo antes de seguir.
3. Si el cambio altera resultados, ejecuta `uv run upistas run` y dime cuántas facturas cambian de resultado.
4. Push de la rama y abre la PR con `gh pr create`:
   - Título con formato de commit y sin número: `feat(fuentes): cargar el Excel de Alberto`.
   - Cuerpo: `Closes #N`, y 2-3 frases normales con qué cambia y por qué. Si cambian resultados, una frase con cuántos. Sin tablas ni checklists.
5. Mueve la tarjeta a "Revisión" y dame el enlace.
