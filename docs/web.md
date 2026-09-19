# La web de Alberto

Es la parte que ve Alberto. Lee nuestra base de datos (lo que el pipeline guardó: documentos, lecturas,
ejecuciones y decisiones) y guarda una sola cosa nueva: lo que Alberto decide sobre las facturas que se le
escalan. Al ERP no escribe nunca; lo único que hace con él es traer copias (ver [ADR-003](adr/003-erp-copia-local.md)).

## Arrancar
```
uv run python manage.py migrate
uv run python manage.py alberto        # crea el usuario alberto / alberto si no existe
uv run python manage.py runserver      # http://127.0.0.1:8000
```
Los datos los pone el pipeline: `uv run upistas run` deja el lote decidido y la web lo enseña. Sin
ninguna ejecución, la portada lo explica y dice cómo lanzarla. Funciona sin internet: htmx y el CSS van
en el repo.

## Pantallas
- **Resumen**: cómo va el lote. Cuántas se pagan, cuántas no y cuántas tiene que mirar él; con qué copia
  del ERP y qué Excel se decidió; cuánto tardó y costó; qué cambió desde la vez anterior; lo primero que
  tiene que mirar.
- **Facturas**: la lista con filtros (resultado, revisadas o no, búsqueda por fichero, pedido, proveedor o
  motivo) y el detalle de cada una con toda su traza: qué dice la norma regla a regla, lo que leímos con
  su confianza y su página, el texto de la factura que no decide, los avisos del fichero, cómo se leyó
  y cuánto costó, el historial en todas las ejecuciones y el PDF original.
- **Para revisar**: la cola de lo escalado, agrupada por motivo. Alberto decide Pagar o No pagar con un
  comentario. Queda guardado aparte (`RevisionHumana`), no toca lo que calculó el sistema, y si dice
  Pagar el pedido cuenta como pagado para los lotes siguientes.
- **Ejecuciones**: cada pasada por un lote con sus cifras, con qué datos se decidió, qué cambió respecto
  a la anterior y la descarga del `outcomes.jsonl` (el fichero de la entrega, línea a línea tal cual).
- **Asientos del ERP** y **Conexión con el ERP**: la copia con la que se decide, su historial y qué cambió
  entre copias.

## Cómo está hecha
- Django: modelos en `web/panel/models.py`; una vista por pantalla en `web/panel/views/`; lo que comparten
  varias pantallas en `web/panel/consultas.py` (qué ejecución vale, lecturas por huella, pendientes de
  revisar, cambios respecto a la anterior, nombres de las reglas en palabras) y los filtros de plantilla
  en `web/panel/templatetags/panel_extras.py`.
- htmx (vendorizado en `static/panel/`) para filtros, paginación y la decisión de Alberto sin recargar la
  página; cada vista devuelve solo el fragmento cuando llega la cabecera `HX-Request`.
- Sesión obligatoria en toda la web (`LoginRequiredMiddleware`); solo la pantalla de entrar queda fuera.
- CSS propio en `static/panel/panel.css` (colores, tarjetas, píldoras, tablas); cada pantalla puede
  añadir el suyo en `static/panel/<pantalla>.css`.

## Tests
`tests/integracion/test_web*.py`, con las fixtures de `tests/integracion/conftest.py`: `alberto` (un
cliente con sesión) y `lote_de_prueba` (cinco facturas con todos los casos y dos ejecuciones, para que
haya cambios que enseñar).

## Lo que no hace (todavía)
- Lanzar el pipeline desde la web: se lanza con `uv run upistas run` y la web lo refleja.
- Usuarios distintos de Alberto ni permisos por pantalla.
