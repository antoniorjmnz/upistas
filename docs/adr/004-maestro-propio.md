# ADR-004: El maestro de proveedores y pedidos vive en nuestra web

- **Estado**: aceptado
- **Fecha**: 2026-09-19
- **Issue**: #38

## Contexto
Hasta ahora, quién es cada proveedor y qué se le pidió salía del Excel de Alberto
(`FINAL_v7_DEFINITIVO_ahorasi.xlsx`), leído entero en cada pasada. Ese Excel es el problema que
vinimos a resolver: hojas de basura, un proveedor repetido, veinte pedidos sin NIF, una hoja
`pendiente_revisar` suelta y nada que impida escribir un IBAN con espacios invisibles. Además, si
Alberto quiere dar de alta a un proveedor o corregir una cuenta, tiene que abrir el Excel, acertar
con la hoja y la columna, guardar y volver a lanzar el repaso.

Los mentores insisten en que el dato es lo importante. Un dato que se corrige a mano en una hoja
de cálculo no se puede validar, ni versionar, ni saber quién lo cambió.

## Decisión
El maestro pasa a ser nuestro: dos tablas en la base de datos de la web (`Proveedor` y `Pedido`)
con un formulario propio, mucho más sencillo que el Excel.

- **Un formulario que no deja meter basura**: NIF con su formato, IBAN normalizado (sin espacios
  ni caracteres invisibles) y de 24 caracteres si es español, importe mayor que cero y número de
  pedido `PO-AAAA-NNNN`. El NIF y el IBAN se guardan ya comparables con lo que se lee de una factura.
- **Más sencillo que el Excel**: el NIF no se repite en cada pedido, lo pone el proveedor; la hoja
  `pendiente_revisar` es una casilla del pedido ("Alberto quiere mirar las facturas de este pedido");
  el `Estado` del Excel, que decía ABIERTO en todos y no era fiable, desaparece.
- **Se conserva el código del proveedor** (P001, P002...): es el nombre con el que el ERP lo llama
  en sus asientos, y sin él no se puede cruzar un pedido con su asiento.
- **Se versiona por contenido**: `MaestroDjango.version` es una huella sha256 (12 caracteres) del
  contenido ordenado de las dos tablas, calculada una vez por instancia. Cambia en cuanto Alberto
  corrige un dato, y va en la `version_datos` de cada ejecución, igual que la versión del ERP. Así
  se sabe con qué maestro se decidió cada factura, como ya se sabía con qué copia del ERP.
- **El ERP sigue siendo la referencia contable y sigue siendo de solo lectura** ([ADR-003](003-erp-copia-local.md)).
  Este maestro sustituye al Excel, no al ERP: si los dos se contradicen sobre un pedido, manda el
  ERP y la factura se escala ([ADR-002](002-criterio.md), punto 10).
- **El Excel no se tira**: `contenedor.maestro()` usa el Excel si se indica a mano (`--excel` o
  `EXCEL_PATH`); si no, nuestras tablas cuando tienen proveedores; y si tampoco, el Excel que
  encuentre. Se puede volver atrás en una orden.

## Cómo entró el dataset de La Caja
Con `uv run python manage.py importar_maestro`, que lee el Excel con el mismo adaptador de siempre
(`MaestroExcel`, con sus limpiezas y sus avisos) y lo vuelca en las tablas. Se puede repetir sin
miedo: actualiza por código y por número, no duplica. Del Excel de La Caja entran 11 proveedores,
516 pedidos y 2 marcados para revisar. Los 2 pedidos de `Pedidos_2025_OLD` se quedan fuera porque
no dicen de qué proveedor son; el comando lo avisa por su nombre.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Seguir leyendo el Excel en cada pasada | Es el origen de casi todas las trampas y no se puede validar al escribir. Alberto tendría que seguir editando hojas. |
| Subir el Excel por la web y guardarlo | Cambia dónde está el fichero, no el problema: seguiría entrando cualquier cosa. |
| Copiar el Excel tal cual a tablas, hoja por hoja | Arrastraría el NIF repetido en cada pedido, el `Estado` que no es fiable y la hoja suelta de revisar. |
| Escribir el maestro en el ERP | El ERP de 2009 no tiene forma de escribir, y aunque la tuviera no tocamos el sistema contable de Alberto. |

## Consecuencias
- Alberto da de alta un proveedor o corrige una cuenta desde la web, en un formulario con sus
  palabras, y el cambio vale para el repaso siguiente sin tocar ningún fichero.
- Cada cambio del maestro cambia la versión de los datos: queda claro qué decisiones se tomaron con
  qué maestro, y se puede reprocesar.
- Los resultados no cambian. La regla del pedido mira primero el asiento del ERP y solo baja al
  maestro si el ERP no tiene ese pedido; y el NIF que hereda un pedido de su proveedor es el mismo
  con el que ya se buscaba al proveedor. Los 20 pedidos del Excel sin NIF dejan de ser un caso raro.
- Riesgo aceptado: el maestro y el Excel pueden separarse si alguien sigue editando el Excel. Se
  asume: a partir de ahora la fuente es la web, y volver al Excel es indicar su ruta.
