# Cómo trabajamos

Chuleta para humanos. Las reglas completas están en [AGENTS.md](AGENTS.md).

Con Claude Code es más fácil: `/tarea 25` para empezar la issue 25 y `/pr` para abrir la PR.

```bash
# una vez tras clonar
sh scripts/setup.sh

# empezar tarea #7
git switch main && git pull
git switch -c 7-trazas

# ...trabajar, commits pequeños...
git commit -m "feat(obs): traza por factura (#7)"

# antes de la PR
git pull --rebase origin main
python scripts/check.py
git push -u origin 7-trazas
gh pr create --fill          # la plantilla pide Closes #7
```

| Situación | Qué hacer |
|---|---|
| Conflicto al hacer rebase | Resolverlo tú en tu rama; si es de otra área, llamar a su owner |
| CI en rojo | No se mergea. Arreglar en la misma rama |
| Necesito cambiar un contrato | PR separada solo con el contrato + aviso al grupo |
| Me he equivocado en `main` | Imposible: `main` está protegida. Crea rama desde tu estado: `git switch -c N-algo` |

## Horas clave
- **Sáb 18:00** lote 2 + norma v4 → nadie mergea cosas grandes entre 17:30 y 19:00.
- **Dom 09:30** congelación de `main`: solo fixes para la entrega.
