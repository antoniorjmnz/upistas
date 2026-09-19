# ADR-003: Copia local y versionada del ERP, de solo lectura

- **Estado**: aceptado
- **Fecha**: 2026-09-19
- **Issue**: #50

## Contexto
Los asientos del ERP de Alberto son la referencia contable para decidir. Pero el bridge de 2009
es lento (0,12 s por petición), falla una de cada diez consultas (`ORA-00600`), limita a 10
peticiones por segundo contando también las rechazadas (`ERP-429`), caduca la sesión a los 15
minutos o 300 consultas, pagina de 20 en 20 en desorden y solo permite consultar un asiento por su
número de asiento, que no siempre coincide con el del pedido. Además, no tiene ninguna forma de
escribir: no se entera de lo que decidimos.

Y los datos cambian: el sábado el lote 2 sobrescribe asientos existentes y el domingo cambiará un
dato. Hay que saber con qué datos se tomó cada decisión y qué cambió.

## Decisión
- **Un único conector** (`adaptadores/fuentes/erp_http.py`) habla con el bridge: descarga todos los
  asientos de una vez, reintenta los `ORA-00600`, espera el `Retry-After` de los 429, vuelve a
  identificarse con `SES-401`, va a 8 peticiones/s para no provocar el límite y comprueba que el
  total descargado cuadra con el que declara el ERP.
- **Copia local versionada** en nuestra base de datos: la versión es una huella del contenido.
  Misma foto del ERP, misma versión; si cambia algo, versión nueva, y queda registrado qué asientos
  cambiaron y a qué pedidos afectan.
- **Historial de sincronizaciones**: cada conexión, buena o mala, con peticiones, reintentos,
  esperas, relogins y duración. Es una señal operativa para Alberto.
- **Las reglas y la web leen la copia**, nunca el bridge en vivo. `upistas run` sincroniza una vez
  al empezar el lote; si el ERP está caído, sigue con la última copia buena y lo dice.
- **Solo lectura, siempre**: nunca escribimos en el sistema contable de Alberto.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Consultar el ERP por cada factura | 500+ consultas a un sistema que falla cada 10 y se bloquea a las 10/s. Además el detalle es por asiento, no por pedido: no se puede buscar una factura directamente. |
| Leer los datos embebidos en `alberto_erp.py` | Sería hacer trampa: en la empresa real no existe ese atajo. Solo se usan en tests. |
| Copia sin versión (sobrescribir cada vez) | Perderíamos con qué datos se decidió cada factura y qué cambió con el lote 2 o el domingo. |
| Paralelizar la descarga | El límite de 10/s manda: en paralelo no se baja de ~3 s y aumenta el riesgo de 429. |

## Consecuencias
- Las decisiones no dependen de que el ERP esté encendido en ese momento.
- La versión de los datos nos da el reprocesado selectivo (#30): solo las facturas de los pedidos afectados.
- Riesgo aceptado: si el ERP cambia y no se sincroniza, se decide con datos viejos. Mitigación:
  cada lote sincroniza al empezar, la web enseña la fecha de la copia en uso y hay un botón para
  sincronizar.

## Evidencia
Medido contra `alberto_erp.py` con la latencia real (no `--rapido`), en un portátil:
- 516 asientos en **3,9-4,0 s** con 30-31 peticiones y 2-3 `ORA-00600` absorbidos.
- Segunda sincronización sin cambios: **misma versión** (`b189d7434436`), sin duplicar nada.
- ERP apagado: se rinde en unos segundos y el lote sigue con la última copia buena.
- Tests: bridge simulado con `ORA-00600`, 429, sesión caducada, total que no cuadra y caída total.
