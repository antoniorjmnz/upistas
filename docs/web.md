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
Los datos los pone el pipeline: `uv run upistas run` deja el lote decidido y la web lo enseña, o los
sube Alberto desde «Subir facturas». Sin ninguna ejecución, la portada lo explica y dice cómo lanzarla.
Funciona sin internet: htmx, el CSS y las letras van en el repo.

## Cómo se escribe cada pantalla
Alberto tiene 60 años y no sabe de informática. De ahí tres reglas que valen para toda la web:

- **Una frase por pantalla.** Arriba del todo, un `.hero`: el título y una sola frase que dice qué es esto
  y qué se puede hacer aquí. Nada de párrafos.
- **Tres colores fijos, siempre con el mismo significado.** Verde se paga, rojo no se paga, ámbar lo decide
  Alberto. El mismo color en la píldora, en el kpi de la portada y en el punto del filtro.
- **Lo técnico, plegado.** Los ids, las huellas, los tokens, el coste, el hardware y los reintentos del ERP
  van dentro de un `details.mas` («Detalles técnicos», «Historial de conexiones»). Fuera del pliegue, solo
  palabras que Alberto usaría.

El sistema de diseño entero está en `static/panel/panel.css` (hero, kpis, cifras, tarjetas, píldoras,
botones, barra de búsqueda con chips, avatares, listas, tablas, avisos, estados vacíos y pliegues) y los
iconos son un tag de plantilla, `{% icono "nombre" %}`, sin ficheros ni red.

## Pantallas
Arriba en la barra lateral, las de Alberto:

- **Subir facturas**: Alberto suelta ahí sus PDF (o un zip con varios dentro), elige el lote y el repaso
  empieza solo, con una barra que se refresca cada segundo hasta que termina y entonces le dice cuántas
  se pagan, cuántas no y cuántas tiene que mirar. Los ficheros se guardan en `almacen/facturas/` con su
  huella por nombre (`MEDIA_ROOT`, fuera de git): la misma factura subida dos veces no ocupa dos veces, y
  lo que no empieza por `%PDF` se rechaza diciéndolo. Se repasa el lote entero, no solo lo nuevo, porque
  leer se cachea por contenido y lo ya leído no se vuelve a leer. El repaso corre en un hilo del propio
  servidor web, y ahí es donde arranca DBOS: en el primer repaso del proceso, una sola vez. Solo se hace
  uno a la vez y su avance vive en memoria (ninguna tabla nueva), así que reiniciar el servidor se lleva
  la barra, no el trabajo: la ejecución y las decisiones ya están guardadas. La misma pasada se puede
  pedir desde la portada con «Repasar ahora», sin subir nada.
- **Hoy**: la portada. De las N facturas del lote, cuántas se pagan, cuántas no y cuántas esperan su
  decisión; lo primero que tiene que mirar; qué cambió desde el repaso anterior.
- **Facturas**: la lista con filtros (resultado, revisadas o no, búsqueda por fichero, pedido, proveedor o
  motivo) y el detalle de cada una con toda su traza: qué dice la norma regla a regla, lo que leímos con
  su confianza y su página, el texto de la factura que no decide, los avisos del fichero, cómo se leyó
  y cuánto costó, el historial en todas las ejecuciones y el PDF original.
- **Proveedores**: el maestro de Alberto, que antes vivía en su Excel ([ADR-004](adr/004-maestro-propio.md)).
  La lista, con buscador por nombre, NIF o código, dice de cada proveedor su cuenta de siempre, cuántos
  pedidos tiene y cuántos ha marcado para mirar; su ficha enseña sus datos, sus pedidos y las facturas
  suyas del último repaso. Se da de alta un proveedor o un pedido con un formulario corto que no deja
  meter basura: el NIF con su formato, el IBAN sin espacios ni caracteres invisibles, el importe mayor
  que cero y el número de pedido `PO-AAAA-NNNN`. El maestro de La Caja entró con
  `uv run python manage.py importar_maestro [--excel RUTA]`, que lee el Excel con el adaptador de
  siempre y lo vuelca en las tablas (11 proveedores y 516 pedidos); se puede repetir sin duplicar nada
  ni pisar lo que Alberto haya marcado o anotado aquí. Las altas del lote 2 entran con el mismo comando
  y `--proveedores-csv` / `--pedidos-csv` (ver «Cómo entra el lote 2» en [backend.md](backend.md)).
- **Importar datos** (`/proveedores/importar/`, el botón «Importar fichero» de Proveedores): si a Alberto le
  mandan un fichero de proveedores o de pedidos como los del lote 2, lo suelta ahí (uno o varios a la vez)
  y la web reconoce cada uno por sus cabeceras (con coma o punto y coma, con o sin BOM; lo que no se
  reconoce o pesa más de 10 MB se rechaza diciéndolo; si trae bytes que no son de ninguna codificación se
  lee igual y avisa arriba). Antes de guardar nada enseña una vista previa con cada fila clasificada
  contra el maestro: nuevo, ya está igual, cambia (qué campo, antes y después) o inválido (NIF raro,
  IBAN que no lo es, campo más largo que su columna, importe que no es un número, fecha que no se
  entiende, pedido de un proveedor que no está ni viene en el mismo envío, fila repetida, mismo NIF con
  dos códigos, otro número de pedido donde iba el estado), con el recuento arriba. Un estado desconocido
  o un NIF que no es el del proveedor no impiden importar (el pedido no guarda ni estado ni NIF): la fila
  entra con un aviso en naranja. «Aplicar» entra solo lo válido por el mismo `MaestroDjango.importar` del comando, así
  que repetirlo no duplica nada, un proveedor que cambia solo actualiza los campos que trae el fichero y
  lo que Alberto marcó o anotó en un pedido no se toca; «Cancelar» no guarda nada. Entre los dos pasos lo
  parseado espera en `almacen/importaciones/<token>.json` (no en la sesión; los de más de un día se
  borran) y cada aplicación queda apuntada en `Importacion`, que es la lista «Últimas importaciones» al
  pie de la pantalla. La lectura y la clasificación están en `web/panel/importaciones.py`, sobre
  `csv_altas.py` y `filas.py`.
- **Para revisar**: la cola de lo escalado, agrupada por motivo. Alberto decide Pagar o No pagar con un
  comentario. Queda guardado aparte (`RevisionHumana`), no toca lo que calculó el sistema, y si dice
  Pagar ese pedido y ese documento cuentan como pagados para los lotes siguientes. Repasar otra vez el
  mismo lote no los da por pagados: la factura vuelve a salir con su resultado de siempre y lo que
  Alberto decidió sigue guardado a su lado.
- **Preguntar**: Alberto pregunta en su idioma y la web contesta con los datos que tiene, con enlace a la
  pantalla donde está la respuesta. Lo hace Fran (#39); el diseño está en [asistente.md](asistente.md).
  Está en un panel lateral que se abre desde cualquier pantalla (y en `/preguntar/` a pantalla entera);
  sabe en qué pantalla está Alberto, le lleva a otra con un botón «Ir a…» y le propone unas pocas cosas
  (marcar un pedido, apuntar una nota o un comentario) que solo se hacen si pulsa «Confirmar». Las
  conversaciones se guardan: «Conversaciones» (arriba del chat) las lista con «Nueva», papelera y
  «Borrar todas», y las tres últimas salen en el menú, bajo «Preguntar». Mientras piensa, una burbuja
  con tres puntos; el proveedor de IA del chat se cambia en el `.env` (`ASISTENTE_*`).

Donde salga una factura hay un botón **Previsualizar**: abre su PDF encima de la página, sin salir de la
lista ni descargar nada. Se cierra con el botón Cerrar, con Escape o pulsando fuera.

Si la factura no se paga sola (no se paga, o la tiene que mirar Alberto, o se paga pero el fichero trae
avisos), al lado hay otro botón: **Ver en el PDF qué ha hecho saltar la alarma**. Abre en el mismo visor
una copia del PDF con cada dato que falla rodeado en naranja y una nota corta al lado («Cuenta distinta de
la del maestro», «Total distinto del pedido: 12.847,40», «Fecha imposible», «Texto que intenta influir
en la decisión»; si dos comprobaciones señalan el mismo dato, una nota debajo de la otra); el texto
escondido va en rojo, como siempre. En la cola de Para revisar el botón solo sale cuando hay algo que
rodear: una factura que solo está ahí porque no se ha podido leer no lo lleva. La copia acaba en una página nueva que
empieza por el resultado y su motivo, lista las alarmas y en qué página está cada una (y lo que no hemos
encontrado escrito en la factura), transcribe lo escondido y dice qué no se ha podido leer. El original no
se toca. Lo decide el caso de uso `aplicacion/marcar_pdf.py` (qué se busca por cada regla y qué se
escribe); PyMuPDF busca y dibuja en `adaptadores/pdf_marcado.py`.

Abajo en la barra lateral, las de quien lleva el sistema (mismo cuidado, más datos):

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
- La piel se llama **Nítida**: una herramienta de trabajo, no un folleto. Barra lateral fija con las
  pantallas de Alberto arriba y las de quien lleva el sistema abajo, cada una con su icono; blanco y gris,
  tarjetas de borde fino, avatares con las iniciales del proveedor y etiquetas con un punto de color. Tres
  colores con significado fijo (verde se paga, rojo no se paga, ámbar lo decide Alberto) e índigo para lo
  que se pulsa. Todo en `static/panel/panel.css`; si una pantalla necesita algo suyo, va en
  `static/panel/<pantalla>.css` y es poco.
- Las letras van en el repo, en `static/panel/fuentes/`: Inter para el texto y Sora para los títulos y las
  cifras, las dos con licencia SIL Open Font License 1.1 (quién es quién, en `fuentes/LICENCIA.txt`). Así
  la web se ve igual sin internet: no se llama a ningún CDN, ni para las letras ni para nada.
- El único JavaScript propio es `static/panel/panel.js`, y solo hace el visor de facturas: cualquier botón
  con `data-pdf` abre ese PDF en el `<dialog>` que está al final de `base.html`, encima de la página. Si el
  navegador no sabe de `<dialog>`, el visor no se activa y la factura se sigue abriendo desde su detalle.
- El gráfico del lote de la portada es un SVG escrito en la plantilla: una rosca con un arco por resultado,
  el total en medio y el reparto en palabras al lado. Sin librería de gráficos.

## Tests
`tests/integracion/test_web*.py`, con las fixtures de `tests/integracion/conftest.py`: `alberto` (el
cliente que abre la web) y `lote_de_prueba` (cinco facturas con todos los casos y dos ejecuciones, para
que haya cambios que enseñar).

## Lo que no hace (todavía)
- Guardar el avance de un repaso: vive en la memoria del servidor, así que al reiniciarlo se pierde la
  barra de progreso (lo repasado no, eso está en la base de datos).
- Usuarios ni permisos por pantalla: la web es de Alberto y se abre sin entrar.
