# Qué hace el backend y qué se ha tenido en cuenta

El backend es todo lo que pasa entre "aquí tienes una carpeta con facturas" y "esta es la decisión
de cada una, con su porqué". La web solo enseña lo que el backend guarda.

## Qué provee

**Una pasada por un lote** (`uv run upistas run --lote lote1`) hace, en este orden:
1. Trae el ERP de Alberto a nuestra copia local (solo lectura). Si el ERP está caído, sigue con
   la última copia buena y lo dice.
2. Lee cada documento de forma duradera: cada fichero es un workflow que queda apuntado. Si el
   proceso se cae, al arrancar sigue por donde iba sin repetir lo hecho. Un contenido ya leído
   (misma huella sha256) no se vuelve a leer aunque llegue con otro nombre o en otro lote.
3. Monta las referencias una vez: proveedores y pedidos del Excel, asientos de la copia del ERP,
   lo que Alberto marcó a mano para revisar, las facturas del propio lote agrupadas por pedido
   (para ver duplicados) y los pedidos ya aprobados en lotes anteriores.
4. Decide todo el lote con la norma (`normas/v3.toml`): rápido, determinista y repetible.
5. Guarda la ejecución con la versión exacta de los datos, cada decisión con sus reglas, alertas y
   notas, y compara con la pasada anterior del mismo lote: qué facturas cambian de resultado y por qué.
6. Escribe `outputs/outcomes.jsonl` (una línea por documento, solo `file_id` y `result` son
   obligatorios; el resto es traza). Si el lote no es `lote1` el fichero se llama
   `outputs/outcomes_<lote>.jsonl` (así el lote 2 sale ya como `outcomes_lote2.jsonl`, el nombre de
   la entrega); `--salida` cambia el nombre.

**Lo que queda guardado** (y la web puede enseñar):
- Cada conexión con el ERP: cuándo, si fue bien, cuántos reintentos, esperas y reconexiones, y qué cambió.
- Cada documento: huella, tipo (texto, escaneado, blanco, roto, cifrado), alertas del fichero.
- Cada lectura: con qué lector y método, qué se sacó (con la confianza y el texto literal de cada
  campo), cuánto tardó y cuántos tokens costó. Las lecturas fallidas también, con el motivo.
- Cada ejecución: lote, norma, versión del ERP y del Excel, hardware, tiempos, resumen.
- Cada decisión: resultado, motivo, reglas que pasó o falló, alertas para Alberto, notas del documento.
- Cada revisión humana: quién decidió qué sobre una factura escalada y cuándo. El original no se toca.

**Comandos**: `upistas erp sync`, `upistas erp estado`, `upistas run [--lote] [--norma] [--carpeta] [--limit] [--sin-sync] [--salida]`.

**También desde la web**: Alberto sube sus PDF en «Subir facturas» y el mismo pipeline los decide en un hilo
del servidor, con barra de progreso; DBOS arranca ahí, dentro del proceso web, en el primer repaso (ver [web.md](web.md)).

**Cómo entra el lote 2.** Tres pasos, sin tocar el Excel de Alberto. (1) Arrancar el ERP con su
actualización: `python alberto_erp.py --puerto 8010 --lote2 erp_export_lote2.csv` (y `ERP_URL` o
`--erp-url` apuntando a ese puerto). (2) Dar de alta los proveedores y pedidos nuevos en el maestro de la web:
`uv run python manage.py importar_maestro --proveedores-csv proveedores_nuevos.csv --pedidos-csv pedidos_nuevos.csv`.
Lee los CSV de La Caja tal cual vienen (`proveedor_id` donde el Excel dice `ProveedorID`) con el adaptador
`fuentes/csv_altas.py`, que devuelve los mismos `Proveedor` y `Pedido` que el Excel, y `MaestroDjango.importar`
los vuelca en las tablas. Con los ficheros reales imprime «4 proveedores nuevos, 39 pedidos nuevos, 0 cambiados»;
repetirlo dice «0 proveedores nuevos, 0 pedidos nuevos, 0 cambiados» y no pisa las marcas de revisar, las notas
ni el campo activo que Alberto haya puesto en la web. (3) Subir la carpeta `facturas_primin` desde «Subir facturas»
o pasarla por línea de comandos:
`uv run upistas run --lote lote2 --facturas facturas_primin --norma v4 --erp-url http://127.0.0.1:8010 --salida outcomes_lote2.jsonl`.

## Qué se ha tenido en cuenta

**El ERP de 2009.** Se descarga entero una vez (el detalle es por número de asiento, no por
pedido, así que no sirve preguntar factura a factura). Reintenta los `ORA-00600`, espera el
`Retry-After` de los 429 sin insistir, vuelve a identificarse cuando caduca la sesión, va por
debajo del límite de 10 peticiones/s y comprueba que el total descargado cuadra. Nunca escribe.

**Los datos cambian.** El sábado el lote 2 sobrescribe asientos y el domingo cambiará un dato. Cada
copia del ERP y cada fichero Excel tienen una versión (huella del contenido); cada ejecución sabe
con qué versión decidió; al volver a pasar un lote se listan las facturas que cambian de resultado.
La norma es un fichero: la v4 es otro fichero, no código nuevo.

**El ERP puede traer dos asientos del mismo pedido** (el lote 2 lo hace con PO-2026-0071). Eso no
para el lote: las referencias guardan todos los apuntes de cada pedido y las reglas miran el que
manda. Si alguno está pagado, manda ese; si todos cuadran, el más reciente; si no cuadran, la
factura se escala diciendo que el ERP tiene dos apuntes que no cuadran (ver [ADR-002](adr/002-criterio.md)).

**Cada lote va con una copia concreta del ERP.** El lote 1 se decidió con la copia del viernes
(516 asientos) y el lote 2 con la del sábado, que trae la actualización (556 asientos y el pedido
PO-2026-0071 pagado). Cada línea del outcome lleva en `version_datos` la huella de la copia con la
que se decidió. Repasar el lote 1 con la copia del sábado cambia exactamente una factura
(`factura_4635`, PAGAR → NO_PAGAR: su pedido aparece pagado después): la entrega del lote 1 se
queda con la copia del viernes, que es la historia real, y el reproceso se enseña como prueba de que
decidir es barato y reproducible. Para repetir una pasada sin hablar con el ERP: `--sin-sync` usa
la última copia guardada.

**Nunca pagar dos veces.** El ERP no se entera de lo que decidimos. Llevamos nuestra propia
memoria: los pedidos aprobados en la última pasada de cada otro lote y los aprobados a mano por una
persona cuentan como pagados para el lote siguiente. Repasar el mismo lote no es pagar dos veces:
ni sus aprobaciones automáticas ni las de Alberto se cuentan contra él. Dentro del mismo lote, las
reglas ven todas las facturas del lote agrupadas por pedido.

**Leer es caro y decidir es barato.** Por eso leer es lo duradero y cacheado (por contenido) y
decidir se repite entero cada vez: reprocesar un lote con una norma nueva cuesta segundos, no
llamadas a la IA.

**Lo que no se puede leer no bloquea el lote.** Un fichero roto, cifrado, en blanco o que ningún
lector entiende acaba en ESCALAR con el motivo exacto, y la pasada sigue. Los lectores se prueban en
orden, del más barato al más caro; el primero que puede, gana.

**Nada del documento se ejecuta ni se obedece.** El inspector solo mira la estructura del fichero y
apunta alertas (JavaScript, ficheros incrustados, caracteres invisibles). Las notas de las facturas
se clasifican y se enseñan; qué hacer con ellas lo dice la norma.

**Dato ausente no es dato ilegible.** Cada campo distingue "seguro que no está" de "no se pudo
leer", porque para la norma lo primero es un incumplimiento y lo segundo una duda.

**Una sola base de datos.** SQLite en local (WAL, transacciones inmediatas para que 16 workers no
se pisen), Postgres con la misma `DATABASE_URL` para escalar. El estado de los workflows y los
datos de la app viven juntos.

**Todo medido, no estimado.** Tiempos de lectura y de decisión, documentos por segundo, tokens y
euros por lectura, hardware de la máquina: quedan en cada ejecución para poder defender las cifras.

## Lo que falta (y de quién es)
- Lectores de PDF: el de texto (#23, hay una propuesta en la PR #58) y los de IA para escaneados (#24). Equipo de lectura.
- Las reglas de la norma (#27): Pablo, sobre `docs/adr/002-criterio.md`.
- Pantallas de Facturas, Para revisar y Resumen (#32, #37): sobre lo que ya guarda el backend.
- Modo de fallos para la demo (#33): timeouts, límites y respuestas inválidas de la IA a voluntad.
