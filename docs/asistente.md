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
3. **No escribe**: ni revisiones, ni pagos, ni nada. Para decidir está la pantalla «Para revisar».
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
`tests/integracion/test_web_asistente.py` con las fixtures `alberto` y `lote_de_prueba` de
`tests/integracion/conftest.py` (cinco facturas con todos los casos, dos ejecuciones):
- cada herramienta devuelve lo que toca con ese lote (por ejemplo, `factura("FA-1016_papelería.pdf")`
  dice No pagar por «ya está pagado según el ERP» y que antes era Pagar);
- la conversación con el modelo falso: el falso pide `factura(...)`, se ejecuta, y la respuesta final
  contiene el enlace a la factura;
- si el modelo lanza timeout, la pantalla devuelve 200 con un aviso y la conversación sigue;
- nunca se llama a nada de escritura (los tests comprueban que no hay `RevisionHumana` nuevas).

## Fuera de alcance
Escribir en nada, consultar el ERP en vivo (se usa la copia), voz, memoria entre sesiones.

## Por dónde empezar
1. Rama desde `32-web-alberto` (o desde main cuando esté fusionada): `git switch -c 39-asistente`.
2. Leer [web.md](web.md) y `web/panel/consultas.py`; hacer primero `herramientas.py` con sus tests, que
   no necesitan IA. Con eso ya hay valor aunque el modelo falle.
3. Después `modelo.py` + `conversacion.py` con el modelo falso, y al final la pantalla.
