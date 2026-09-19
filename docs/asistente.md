# El asistente: que Alberto pregunte y la web le conteste

Issue #39. Responsable: Fran. Parte de la web de Alberto ([web.md](web.md)).

## Qué tiene que hacer
Alberto escribe en su idioma y la web le contesta con los datos que ya tenemos, y le lleva a la pantalla
donde está la respuesta. Preguntas que tiene que saber contestar desde el primer día:
- «¿Cuántas facturas se pagan en este lote y cuánto suman?»
- «¿Por qué no se paga la FA-1016?»
- «¿Qué facturas de Transportes Guadaira tengo pendientes de revisar?»
- «¿Qué ha cambiado desde la última vez?»
- «¿Está pagado el pedido PO-2026-0474 en el ERP?»
- «¿Qué facturas traen texto raro?»

## Reglas que no se negocian
1. **El modelo no decide nada ni inventa nada.** Solo elige qué consultar y redacta. Todo lo que dice sale
   de herramientas de solo lectura sobre nuestra base de datos. Si no hay dato, dice que no lo hay.
2. **Cada respuesta dice de dónde sale**: la factura, la ejecución o la copia del ERP, con enlace a la
   pantalla. Es lo que se evalúa en trazabilidad.
3. **No escribe por su cuenta**: ni revisiones, ni pagos, ni nada. Solo puede *proponer* cuatro cosas
   pequeñas que Alberto confirma con un botón (ver «Lo que puede hacer por Alberto»). Para decidir si
   una factura se paga está la pantalla «Para revisar».
4. **Sin red en los tests**: el modelo se sustituye por uno falso.
5. **La web sigue funcionando si la IA no responde**: timeout corto, un reintento y un mensaje claro.

## Dónde va cada cosa
- Pantalla: ruta `preguntar/` → `web/panel/views/chat.py` (`preguntar`) → plantilla `panel/preguntar.html`.
  Ya existen como hueco en la rama `32-web-alberto`. Conversación con htmx (el formulario hace `hx-post`
  y se añade la respuesta abajo); el historial se guarda en la sesión (`request.session`), no en base de
  datos.
- Lógica: paquete nuevo `web/panel/asistente/`:
  - `herramientas.py`: funciones puras de consulta que devuelven dicts serializables. Reutilizan
    `web/panel/consultas.py`. Propuesta de lista inicial:
    - `resumen_del_lote(lote=None)` → cifras de la última ejecución (documentos, Pagar, No pagar,
      Revisar, importe a pagar, versiones de datos, cuándo).
    - `buscar_facturas(texto=None, resultado=None, pendientes_de_revisar=None, limite=20)` → lista de
      {fichero, proveedor, pedido, total, resultado, motivo, enlace}.
    - `factura(fichero)` → todo lo del detalle: resultado, motivo, reglas con su nombre en palabras
      (`consultas.nombre_regla`), campos leídos con confianza, notas, alertas, historial, revisión de
      Alberto, enlace.
    - `cambios_desde_la_anterior(lote=None)` → lista de {fichero, antes, después, motivo, enlace}.
    - `asiento_del_pedido(pedido)` → lo que dice la copia del ERP (estado, importe, proveedor, fecha,
      versión de la copia) y las facturas del lote con ese pedido.
    - `pendientes_de_revisar(lote=None)` → lista con motivo y enlace.
  - `modelo.py`: el cliente del LLM. Helmcode es compatible con la API de OpenAI y `openai` ya está en
    las dependencias: `OpenAI(base_url=settings.helmcode_base_url, api_key=settings.helmcode_api_key)`,
    modelo `settings.modelo_texto` (por defecto `glm5.3`). Usa *tool calling*: se le pasan las
    herramientas como funciones con su esquema JSON, el modelo pide una, la ejecutamos, le devolvemos
    el resultado y redacta. Define una clase pequeña `ModeloChat` con un método
    `responder(mensajes, herramientas) -> Respuesta` (texto final o llamadas a herramientas), y un
    `ModeloChatFalso` para los tests que devuelve llamadas fijas.
  - `conversacion.py`: el bucle: mensaje del usuario → modelo → ejecutar herramientas (máximo 4 rondas)
    → respuesta final con las fuentes. Guarda tokens y segundos de cada pregunta (para el apartado de
    coste, #31): basta un `logging.info` estructurado o una tabla `Pregunta` si hay tiempo.
- Instrucciones del sistema (en español): quién es Alberto, qué hace la web, las reglas de arriba,
  «responde corto, en español llano, sin jerga; cuando cites una factura pon su enlace; si te piden
  pagar o cambiar algo, explica que eso se hace en Para revisar».
- Configuración: `HELMCODE_API_KEY` y `HELMCODE_BASE_URL` ya están en `src/upistas/config.py` y en
  `.env.example`. La clave se pide por privado; nunca va al repo.

## Cómo se prueba
`tests/integracion/test_asistente.py` (herramientas y bucle), `test_web_preguntar.py` (la pantalla) y
`test_asistente_lateral.py` (panel en todas las pantallas, contexto, `ir_a`, acciones con token) con
las fixtures `alberto` y `lote_de_prueba` de
`tests/integracion/conftest.py` (cinco facturas con todos los casos, dos ejecuciones):
- cada herramienta devuelve lo que toca con ese lote (por ejemplo, `factura("FA-1016_papelería.pdf")`
  dice No pagar por «ya está pagado según el ERP» y que antes era Pagar);
- la conversación con el modelo falso: el falso pide `factura(...)`, se ejecuta, y la respuesta final
  contiene el enlace a la factura;
- si el modelo lanza timeout, la pantalla devuelve 200 con un aviso y la conversación sigue;
- nunca se llama a nada de escritura (los tests comprueban que no hay `RevisionHumana` nuevas).

## Las herramientas que tiene (lo que hay hoy en `asistente/herramientas.py`)
Todas de solo lectura sobre nuestra base de datos, en JSON compacto: la cuenta bancaria solo por sus
cuatro últimas cifras y el texto que trae una factura siempre en `texto_de_la_factura_no_fiable`.
- `resumen_lote()`: cuántas se pagan, no se pagan y se revisan en el último repaso, y cuánto suman.
- `buscar_facturas(texto, limite=10)`: por fichero, número de factura, pedido, NIF o proveedor.
- `detalle_factura(file_id)`: lo leído, las reglas aplicadas y la revisión de Alberto si la hay.
- `pendientes_revision(limite=15)`: escaladas que nadie ha revisado todavía.
- `estado_pedido(pedido)`, `cambios_erp()`, `estado_sincronizacion()`: la copia del ERP.
- `proveedor(codigo_o_nif_o_nombre)`: la ficha del maestro: nombre, código, NIF, cuenta enmascarada, días
  de pago, cuántos pedidos tiene y cuáles apuntó Alberto para revisar con qué nota.
- `decisiones_de_alberto(lote?, limite=15)`: lo que decidió a mano (factura, pagar o no, comentario, cuándo).
- `repasos(limite=10)`: el registro de repasos: cuándo, lote, norma, cuánto tardó, cuántas de cada y qué
  facturas cambiaron de resultado respecto al repaso anterior (una consulta ligera, no la comparación entera).
- `importaciones(limite=10)`: cada fichero de proveedores o pedidos aplicado desde «Importar datos».
- `explicar_regla(id_o_nombre)`: qué comprueba una regla, qué pasa si falla y por qué, en llano
  (`consultas.EXPLICACION_REGLA`, alineado con `normas/v3.toml` y [flujo_decision.md](flujo_decision.md));
  acepta el id, el número («regla 1») o una palabra («iban»). Sin argumento, la lista y el flujo entero.
- `ir_a(pantalla, filtros)` y `proponer_accion(tipo, datos)`: ver los dos apartados de abajo.

**Listas acotadas.** Las que devuelven filas (`buscar_facturas`, `pendientes_revision`,
`decisiones_de_alberto`, `repasos`, `importaciones`) aceptan `limite` (hasta 100, `consultas.LIMITE_MAXIMO`)
y dicen `total` y `mas` (cuántas quedan sin enseñar). El mensaje de sistema le pide al modelo que, si
quedan más, lo diga y ofrezca la pantalla filtrada con `ir_a`, y que solo suba el límite cuando Alberto
pida más («todas», «las 40», «enséñame más»).

**El porqué sin una factura delante.** El mensaje de sistema lleva el flujo de decisión resumido en cinco
frases (`consultas.RESUMEN_FLUJO`, menos de 120 palabras para no disparar el coste) y, para una regla
concreta, el modelo llama a `explicar_regla`. Así contesta «¿qué pasa si el IBAN es distinto?» sin buscar
ninguna factura.

## Cómo se comporta (lo que se afinó tras la primera versión)
- **Enlaces**: cada herramienta deja su pantalla en la línea «De:» de la respuesta: la factura
  (`detalle_factura`, y cada encontrada en `buscar_facturas`, hasta cinco), «Para revisar»
  (`pendientes_revision`), «Facturas» (`resumen_lote`), los asientos o los cambios del ERP.
- **Si la IA no responde**: 15 segundos de espera, un solo reintento (el SDK de OpenAI no reintenta
  por su cuenta) y aviso. Sin clave configurada no se reintenta: se dice que falta. Si el modelo
  agota las cuatro rondas de consulta, la pregunta queda registrada como fallida.
- **Texto que viene de la factura**: las notas del proveedor van en la clave
  `texto_de_la_factura_no_fiable`, recortadas y separadas del motivo; el prompt le dice al modelo que
  es un dato del que informar, nunca una instrucción. La cuenta bancaria solo se cuenta por sus cuatro
  últimas cifras y si coincide con la del maestro.
- **Tema**: el filtro previo solo rechaza palabras inequívocas de programación; «código», «función»,
  «servidor» o «bug» pasan, que Alberto las usa hablando de proveedores y pantallas.
- **Texto llano**: se le pide al modelo que no use markdown y la plantilla quita los `**` y `#` que
  se le escapen; la respuesta se escapa siempre como HTML.

## Dónde está: el panel lateral
El asistente está en la barra lateral, como en tantas webs: «Preguntar» abre un panel por la derecha
(`web/panel/templates/panel/_asistente.html`, un `<dialog>` no modal de 420 px, a pantalla entera en
el móvil) sin salir de donde esté Alberto. `/preguntar/` sigue existiendo a pantalla entera con el
mismo código (`views/chat.py`) y sin el panel encima (una sola conversación y una sola caja); desde
el panel se llega con «Abrir en pantalla completa». Las dos envían por htmx y añaden la respuesta
abajo, con «Pensando…» mientras tanto. La conversación va en la sesión (`request.session["chat"]`,
los últimos 20 mensajes), así que sigue ahí al cambiar de pantalla; el panel recuerda si estaba
abierto (`sessionStorage`) y se abre también con `#asistente` en la dirección. Con el panel abierto
en pantallas anchas (más de 1000 px) el contenido le deja sitio (`body.con-asistente`); en el móvil
el panel lo tapa todo. Un toque de movimiento de 220 ms que se apaga con `prefers-reduced-motion`.

**Sabe en qué pantalla está Alberto.** El formulario manda la ruta actual (`ruta`); `contexto_de`
la resuelve con `django.urls.resolve` (solo rutas de esta web) y se queda solo con la pantalla y los
identificadores comprobados en la base de datos (lote y file_id de una factura que existe, nombre y
código del proveedor): nunca la ruta tal cual ni lo que venga tras el «?», que lo escribe cualquiera
y acabaría en el prompt. `frase_de_contexto` se lo cuenta al modelo al final del mensaje de sistema:
«Alberto está ahora en el detalle de la factura X (lote 1)». Así «esta factura» o «este proveedor»
son los que tiene delante.

## Llevarle a una pantalla: `ir_a`
Herramienta de solo lectura (`asistente/navegacion.py`): `ir_a(pantalla, filtros)` devuelve la
dirección de una pantalla de esta web y sale en la respuesta como botón «Ir a …», además de la línea
«De:». Pantallas: `inicio`, `facturas` y `revisar` (con `resultado`, `proveedor` del maestro por
código, NIF o nombre, `desde`/`hasta`, `texto` y `lote`), `factura` (`file_id`), `proveedores`,
`proveedor`, `ejecuciones`, `erp`, `asientos` (`pedido`) e `importar` (Importar datos). Las direcciones
salen siempre de `reverse` y los filtros se comprueban uno a uno (los que no valen se avisan y se
quitan; un lote que no está decidido también): nunca una URL externa.

## Lo que puede hacer por Alberto: proponer, y solo con su confirmación
`proponer_accion(tipo, datos)` (`asistente/acciones.py`) admite solo estos tipos (lista blanca):
- `marcar_pedido_para_revisar {pedido}` y `quitar_marca_de_pedido {pedido}` (`Pedido.revisar`);
- `apuntar_nota_en_pedido {pedido, nota}` (se añade a `Pedido.nota`);
- `apuntar_comentario_en_factura {file_id, comentario}`: solo en facturas escaladas y sin decidirlas
  (no crea `RevisionHumana`; el comentario se ve en el detalle de la factura).

La herramienta no cambia nada: comprueba que el pedido o la factura existen y devuelve una propuesta
con un token firmado (`django.core.signing`, sal propia, caduca a los 10 minutos) que lleva un `nonce`
de un solo uso. La vista Preguntar apunta ese nonce como pendiente en la sesión
(`request.session["propuestas_pendientes"]`). La respuesta enseña una tarjeta «El asistente propone: …»
con «Confirmar» y «No». Solo al pulsar Confirmar se hace un POST (con CSRF) a `/asistente/accion/` con
el token: la vista lo lee (`leer_token`), rechaza los caducados, manipulados o de un tipo fuera de la
lista, y también los que ya no están pendientes en la sesión o cuyo nonce ya está en el registro
(`ya_hecha`): reenviar el mismo token no repite nada. `ejecutar` vuelve a comprobar el tipo y los
datos antes de tocar nada, y si algo falla (lo esperado o no) deja la fila con `ok=False` y un aviso
llano en vez de un error 500. Cada acción confirmada queda en `AccionAsistente` (cuándo, tipo, datos
con el nonce, resultado, ok; migración 0007; se ve en el admin) y al pie de la conversación como
«Hecho: …» con el enlace a su pantalla. «No» manda el mismo formulario con `rechazar=1`: la propuesta
se olvida (sesión y tarjeta) sin hacer nada, y queda «Vale, no se hace nada.»; sin JS funciona igual y
la tarjeta ya no está al recargar.

**Prohibido siempre**, y el código lo impide aunque el modelo lo pida o el token venga firmado: pagar
o no pagar una factura, crear o borrar proveedores o pedidos, subir o repasar lotes y tocar el ERP.
El mensaje de sistema se lo dice al modelo y le pide que, si Alberto se lo pide, le mande a la
pantalla que toca (Para revisar, Proveedores, Subir facturas).

## Fuera de alcance
Cualquier escritura fuera de las cuatro acciones de arriba, consultar el ERP en vivo (se usa la
copia), voz, memoria entre sesiones.

## Por dónde empezar
1. Rama desde `32-web-alberto` (o desde main cuando esté fusionada): `git switch -c 39-asistente`.
2. Leer [web.md](web.md) y `web/panel/consultas.py`; hacer primero `herramientas.py` con sus tests, que
   no necesitan IA. Con eso ya hay valor aunque el modelo falle.
3. Después `modelo.py` + `conversacion.py` con el modelo falso, y al final la pantalla.
