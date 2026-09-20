# Poner al día las issues de GitHub con lo que has hecho

Copia este texto entero y pégaselo a tu Claude (o a quien uses) en tu carpeta del repo. Es un encargo
cerrado: no cambia código, solo deja GitHub contando la verdad de lo que has hecho.

---

Estás en el repo `antoniorjmnz/upistas` (hackathon "500 Sombras de Alberto"). Yo soy uno de los cuatro del
equipo y he hecho trabajo que no está bien reflejado en las issues. Tu tarea es poner GitHub al día con
lo que YO he hecho, y nada más. Trabaja con `gh` (ya está autenticado) y con git. No toques código, no
crees ramas, no hagas push de nada que no sean comentarios, etiquetas, asignaciones y cierres de issues.

Primero lee `CLAUDE.md`, `AGENTS.md` y `docs/contexto.md` para saber cómo escribimos: español normal,
corto, sin tablas, sin emojis, sin frases de relleno. Un comentario de issue son dos o cinco líneas.

Pasos:

1. Averigua qué he hecho yo. Mi usuario de GitHub es `[TU_USUARIO]`. Mira:
   - `git log --author="[TU_USUARIO]" --oneline --all` y también con mi nombre o correo si el autor no
     coincide (`git log --format="%h %an %ae %s" --all | head -100` para ver cómo aparezco).
   - `gh pr list --author [TU_USUARIO] --state all` y `gh pr view N --json title,body,files,mergedAt`.
   - Mis ramas: `git branch -a | grep -i [algo mío]`.
   Hazme una lista corta: qué piezas he hecho, en qué ficheros, en qué PR o commit, y si está fusionado.
   Enséñamela y espera a que la confirme antes de tocar GitHub.

2. Cruza esa lista con las issues abiertas: `gh issue list --state all --limit 100`. Para cada pieza mía:
   - Si hay una issue que la cubre: escribe un comentario con qué se hizo, dónde está (PR o commit) y qué
     queda pendiente si algo. Si está terminada y fusionada, ciérrala con `gh issue close N --comment "..."`.
     Si está a medias, déjala abierta y di en el comentario qué falta.
   - Si no hay issue: créala con `gh issue create`, título corto en infinitivo o nombre ("Lector OCR de
     escaneados con fal.ai"), cuerpo de tres líneas (qué es, dónde está, estado), asígnamela
     (`--assignee [TU_USUARIO]`), ponle el milestone que toque (`Lote 1`, `Lote 2 y demo` o `Entrega`)
     y ciérrala en el mismo paso si ya está hecha y fusionada.
   - Asígnate las issues en las que has trabajado (`gh issue edit N --add-assignee [TU_USUARIO]`).

3. Tablero: el proyecto es el número 2 del usuario `antoniorjmnz`. Para cada issue que hayas tocado,
   pon la tarjeta en la columna que corresponde (`Hecho` si está cerrada, `En curso` si sigues con ella,
   `Revisión` si tiene PR abierta). Se hace así:
   ```
   ITEM=$(gh project item-list 2 --owner antoniorjmnz --format json --limit 200 | python -c "import json,sys; d=json.load(sys.stdin); print(next((i['id'] for i in d['items'] if i.get('content',{}).get('number')==N), ''))")
   gh project item-edit --id "$ITEM" --project-id PVT_kwHOAuWNas4Bj85H --field-id PVTSSF_lAHOAuWNas4Bj85HzhivWpo --single-select-option-id OPCION
   ```
   con `N` el número de la issue y `OPCION` una de: `18a46e28` (To do), `3a23c58f` (En curso),
   `efc63bbd` (Revisión), `8407b068` (Hecho). Si una issue mía no está en el tablero, añádela:
   `gh project item-add 2 --owner antoniorjmnz --url https://github.com/antoniorjmnz/upistas/issues/N`.

4. Mis PR: si alguna tiene la descripción vacía o dice cosas que ya no son verdad, corrígela con
   `gh pr edit N --body "..."` (qué cambia, por qué, qué issue cierra; corto). No fusiones nada.

5. Al final dame un resumen de diez líneas como mucho: issues comentadas, cerradas, creadas, tarjetas
   movidas, y lo que no has sabido dónde encajar para que lo decida yo.

Reglas: no inventes trabajo que no esté en git; si dudas de si algo es mío, pregúntame; no cierres
issues de otros; no cambies títulos de issues que no sean mías; y todo en español normal.

---

Antes de mandárselo a nadie: sustituye `[TU_USUARIO]` por el usuario de GitHub de cada uno
(pablosaez21, fjvilpal, Xavier595).
