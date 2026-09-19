# La web de Alberto

Es la parte que ve Alberto. Lee nuestra base de datos (lo que el pipeline guardó: documentos, lecturas,
ejecuciones y decisiones) y guarda una sola cosa nueva: lo que Alberto decide sobre las facturas que se le
escalan. Al ERP no escribe nunca; lo único que hace con él es traer copias (ver [ADR-003](adr/003-erp-copia-local.md)).

No hay usuarios ni contraseña: la web se abre y ya está. Alberto es quien la abre.

## Arrancar
```
uv run python manage.py migrate
uv run python manage.py runserver      # http://127.0.0.1:8000
```
Los datos los pone el pipeline: `uv run upistas run` deja el lote decidido y la web lo enseña. Sin
ninguna ejecución, la portada lo explica y dice cómo lanzarla. Funciona sin internet: htmx y el CSS van
en el repo.

## Cómo se escribe cada pantalla
Alberto tiene 60 años y no sabe de informática. De ahí tres reglas que valen para toda la web:

- **Una frase por pantalla.** Arriba del todo, un `.hero`: el título y una sola frase que dice qué es esto
  y qué se puede hacer aquí. Nada de párrafos.
- **Tres colores fijos, siempre con el mismo significado.** Verde se paga, rojo no se paga, ámbar lo decide
  Alberto. El mismo color en la píldora, en el montón y en el punto del filtro.
- **Lo técnico, plegado.** Los ids, las huellas, los tokens, el coste, el hardware y los reintentos del ERP
  van dentro de un `details.mas` («Detalles técnicos», «Historial de conexiones»). Fuera del pliegue, solo
  palabras que Alberto usaría.

El sistema de diseño entero está en `static/panel/panel.css` (hero, montones, cifras, tarjetas, píldoras,
botones, barra de búsqueda con chips, listas, tablas, avisos, estados vacíos y pliegues) y los iconos son
un tag de plantilla, `{% icono "nombre" %}`, sin ficheros ni red.

## Pantallas
En la cabecera, las de Alberto:

- **Hoy**: la portada. De las N facturas del lote, cuántas se pagan, cuántas no y cuántas esperan su
  decisión; lo primero que tiene que mirar; qué cambió desde el repaso anterior.
- **Facturas**: la lista con filtros (resultado, revisadas o no, búsqueda por fichero, pedido, proveedor o
  motivo) y el detalle de cada una con toda su traza: qué dice la norma regla a regla, lo que leímos con
  su confianza y su página, el texto de la factura que no decide, los avisos del fichero, cómo se leyó
  y cuánto costó, el historial en todas las ejecuciones y el PDF original.
- **Para revisar**: la cola de lo escalado, agrupada por motivo. Alberto decide Pagar o No pagar con un
  comentario. Queda guardado aparte (`RevisionHumana`), no toca lo que calculó el sistema, y si dice
  Pagar el pedido cuenta como pagado para los lotes siguientes.
- **Preguntar**: Alberto pregunta en su idioma y la web contesta con los datos que tiene, con enlace a la
  pantalla donde está la respuesta. Lo hace Fran (#39); el diseño está en [asistente.md](asistente.md).

En el pie, las de quien lleva el sistema (mismo cuidado, más datos):

- **Registro de repasos**: cada pasada por un lote en una línea (cuándo, lote, facturas, se pagan, no se
  pagan, para revisar, duración y estado) y el detalle de una: la misma frase de la portada, las cuatro
  cifras, qué cambió respecto al repaso anterior, la descarga del `outcomes.jsonl` (el fichero de la
  entrega, línea a línea tal cual) y, plegado, con qué datos se decidió, cuánto tardó y costó y en qué
  ordenador se hizo.
- **Conexión con el ERP**: la copia con la que se trabaja, sus cifras, el botón de sincronizar y, plegado,
  el historial de conexiones con sus reintentos y qué cambió entre copias.
- **Asientos del ERP**: los asientos de una copia, con buscador, chips de estado y el selector de copia.

## Cómo está hecha
- Django: modelos en `web/panel/models.py`; una vista por pantalla en `web/panel/views/`; lo que comparten
  varias pantallas en `web/panel/consultas.py` (qué ejecución vale, lecturas por huella, pendientes de
  revisar, cambios respecto a la anterior, nombres de las reglas en palabras) y los filtros de plantilla
  en `web/panel/templatetags/panel_extras.py`.
- htmx (vendorizado en `static/panel/`) para filtros, paginación y la decisión de Alberto sin recargar la
  página; cada vista devuelve solo el fragmento cuando llega la cabecera `HX-Request`. Todo funciona
  también sin JavaScript: los formularios se envían y las páginas se recargan.
- CSS propio en `static/panel/panel.css`; si una pantalla necesita algo suyo, va en
  `static/panel/<pantalla>.css` y es poco.

## Tests
`tests/integracion/test_web*.py`, con las fixtures de `tests/integracion/conftest.py`: `alberto` (el
cliente que abre la web) y `lote_de_prueba` (cinco facturas con todos los casos y dos ejecuciones, para
que haya cambios que enseñar).

## Lo que no hace (todavía)
- Lanzar el pipeline desde la web: se lanza con `uv run upistas run` y la web lo refleja.
- Usuarios ni permisos por pantalla: la web es de Alberto y se abre sin entrar.
