---
description: Empezar a trabajar en una issue del tablero
argument-hint: <número de issue>
---
Vamos a trabajar en la issue #$ARGUMENTS.

1. Lee la issue con `gh issue view $ARGUMENTS --comments`. Si no has leído `docs/contexto.md` en esta sesión, léelo.
2. Asígnamela (`gh issue edit $ARGUMENTS --add-assignee @me`) y muévela a "En curso" en el tablero.
3. Actualiza main y crea la rama: `git switch main && git pull && git switch -c $ARGUMENTS-<slug-corto>`.
4. Mira en `docs/arquitectura.md` en qué capa va el trabajo y qué ficheros tocar. Explícame el plan en 3-5 líneas y espera mi visto bueno antes de programar.
5. Al programar: tests primero para la lógica de dominio, commits de una línea `tipo(área): qué (#$ARGUMENTS)`.
