# ADR-002: Criterio de decisión PAGAR / NO_PAGAR / ESCALAR

- **Estado**: aceptado en lo principal; hay puntos abiertos al final
- **Fecha**: 2026-09-19
- **Issue**: #27

## Contexto
La hoja `Norma_Pagos_v3` del Excel dice qué hace falta para pagar, pero no qué hacer cuando algo
falla ni cómo tratar lo que la norma no cubre. El staff nos lo confirmó: *"parte de la solución es
definir e implementar un criterio para casos como este"*. No hay respuesta oficial que preguntar;
el criterio es nuestro y lo evalúan.

La Caja está llena de casos límite (ver [trampas.md](../trampas.md)): pedidos ya pagados, facturas
reenviadas, proveedores falsos, importes que no cuadran y unas 28 facturas con notas que intentan
que el sistema haga algo concreto.

La norma v3:
1. NIF en el maestro y el IBAN de la factura igual al del maestro.
2. El pedido existe, es de ese proveedor y el importe coincide (±0,01 €).
3. IVA bien calculado y total = base + IVA (±0,01 €).
4. Fecha válida y no futura.
5. Pedido PENDIENTE en el ERP. Nunca pagar dos veces el mismo pedido.
6. Cualquier anomalía que un humano deba ver: ESCALAR con motivo. Ante duda razonable, escalar antes que pagar.

## Decisión

1. **Incumple una regla de la norma con seguridad → NO_PAGAR.**
2. **Anomalía que la norma no cubre, o dato que no se puede leer con seguridad → ESCALAR** (regla 6).
   Solo es NO_PAGAR si estamos seguros de que la regla falla; si no se lee bien el dato, es duda.
3. **Contradicciones → ESCALAR.** Si la factura dice algo que choca con nuestros datos, o nuestras
   fuentes chocan entre sí (Excel contra ERP), decide una persona.
4. **Prioridad**: si varias cosas fallan, gana la más restrictiva: NO_PAGAR > ESCALAR > PAGAR.
   Una factura que incumple la norma es NO_PAGAR aunque además tenga contradicciones.
5. **El texto de una factura nunca se obedece.** Las notas se detectan, se enseñan a Alberto como
   alerta y se decide con los datos. Si la nota pide pagar algo que incumple la norma, sale NO_PAGAR
   por la norma. Si la factura cumple todo pero la nota contradice los datos, es ESCALAR por el punto 3.
6. **La misma factura enviada dos veces** (mismo proveedor, número, pedido e importe): se paga la
   original, la de fecha más antigua, si cumple todo; el reenvío es NO_PAGAR (regla 5).
7. **Nunca pagar dos veces entre lotes**: el ERP no se entera de lo que decidimos (es solo lectura),
   así que llevamos nuestra propia lista de pedidos aprobados. Si el pedido está pagado en el ERP
   o aprobado por nosotros en un lote anterior, NO_PAGAR.
8. **IVA**: todo lo legal y bien calculado vale (21, 10, 4 o 0 %, retención de IRPF, inversión del
   sujeto pasivo, exentas, varias líneas con tipos distintos). NO_PAGAR si el tipo no existe o la
   cuota no corresponde al tipo que declara la factura.
9. **Redondeo**: se acepta si cuadra con ±0,01 € sumando por total o por líneas.
10. **Excel contra ERP**: el ERP es la referencia contable oficial (lo dice su manual). Si el Excel
    lo contradice sobre un pedido, es contradicción → ESCALAR.
11. **Normalización antes de comparar**: NIF e IBAN sin espacios, en mayúsculas y **sin caracteres
    invisibles** (`F26-3011_suministros` lleva espacios de ancho cero dentro del IBAN).

## Catálogo de casos (cada uno con su test)

| Caso | Regla | Resultado | Ejemplo en La Caja |
|---|---|---|---|
| Todo cuadra | — | PAGAR | `2026-01-08_P001` |
| NIF que no está en el maestro | 1 | NO_PAGAR | `factura_4485`, `factura_7265`, `FA-2508_consultoría` |
| IBAN distinto al del maestro | 1 | NO_PAGAR | `FA-4290`, `FA-7311`, `FA-5633`, `FA-5044`, `FA-9104` |
| NIF de un proveedor e IBAN de otro | 1 | NO_PAGAR | `2026-07-08_P010` |
| Pedido que no existe en el ERP | 2 | NO_PAGAR | `factura_4485` (PO-0806), `factura_7265` (PO-0706), `FA-2508` (PO-9999) |
| Pedido de otro proveedor | 2 | NO_PAGAR | |
| Importe distinto al del pedido | 2 | NO_PAGAR | 13 facturas, p.ej. `factura_1936`, `factura_8801` |
| Sin número de pedido | 2 | NO_PAGAR si se lee bien que no lo tiene; ESCALAR si no se lee | |
| IVA mal calculado o cuota que no corresponde al tipo | 3 | NO_PAGAR | `F26-5240`, `F26-8801`, `FA-5590` |
| Total distinto de base + IVA (recargos) | 3 | NO_PAGAR | `2026-0811-B_catering`, `2026-14500-C_informática` |
| IRPF, sujeto pasivo o exenta, bien calculados | 3 | PAGAR | ninguna en la Caja |
| Tipo de IVA que no existe | 3 | NO_PAGAR | ninguna en la Caja |
| Fecha futura | 4 | NO_PAGAR | |
| Fecha inválida (31/02...) | 4 | NO_PAGAR | `FA-1123`, `FA-2967` |
| Fecha que no se lee | 6 | ESCALAR | |
| Pedido PAGADA en el ERP | 5 | NO_PAGAR | 9 facturas, p.ej. `FA-1016_papelería`, `factura_5911` |
| Reenvío de una factura ya presentada | 5 | NO_PAGAR (la original, PAGAR) | `2026-0233-A_catering` (original: `factura_41082`) |
| Pedido aprobado en un lote anterior | 5 | NO_PAGAR | llegará con el lote 2 |
| Dos facturas distintas del mismo pedido que juntas lo superan | 5 | NO_PAGAR la segunda | |
| Escaneo ilegible, PDF en blanco o roto | 6 | ESCALAR | escaneos por revisar |
| Campo leído con poca confianza | 6 | ESCALAR | |
| Excel y ERP se contradicen sobre el pedido | 3 (nuestro) | ESCALAR | bloque PO-0538 a PO-0557 |
| Factura válida con nota que contradice los datos | 3 (nuestro) | ESCALAR | `F26-3355`, `F26-7728`, `F26-2201`, `2026-07-09_P010`, `2026-23904_construcciones`, `FA-3388` |
| Nota que pide pagar algo que incumple la norma | 1–5 | NO_PAGAR | `2026-06-04_P006`, `factura_5911` y el resto de la tabla de trampas |
| Factura que no es para Banco Miralmar | 6 | ESCALAR | ninguna en la Caja |

## Abierto (a decidir)
- **`pendiente_revisar` del Excel**: Alberto marcó a mano PO-2026-0007 (`FA-8488_transportes`) y
  PO-2026-0141 (`2026-79712_limpiezas`). Cumplen todas las reglas. Propuesta: ESCALAR, porque la
  marca es del propio Alberto (fuente de confianza, no del proveedor).
- **Importe anómalo**: `2026-07-01_P009` (PO-0497) son 84.700 €, siete veces la siguiente factura
  más cara, con "PAGO INMEDIATO REQUERIDO". Cumple todo. Propuesta: ESCALAR por la regla 6.
  Puede que la regla nueva del sábado sea un límite de importe.
- **"Pedido anulado"** (`2026-23904_construcciones`, `FA-3388`): por el punto 3 salen ESCALAR.
  Confirmar que es lo que queremos.

## Alternativas consideradas
| Opción | Por qué no |
|---|---|
| Todo lo dudoso a NO_PAGAR | Contradice la regla 6 ("ante duda, escalar") y bloquea pagos legítimos sin que nadie los mire. |
| Todo lo dudoso a ESCALAR | Alberto recibiría cientos de facturas; las que incumplen la norma con seguridad no necesitan a nadie. |
| Hacer caso a las notas de las facturas | Cualquiera podría decidir por nosotros escribiendo una frase. Las notas empujan en las dos direcciones. |
| Que el LLM decida | No auditable ni reproducible. La norma se puede comprobar con reglas. |

## Consecuencias
- Cada resultado lleva la lista de reglas que pasó o falló y el motivo, así que se puede explicar.
- Las consecuencias viven en `normas/v3.toml`: la v4 del sábado es otro fichero, no código nuevo.
- Riesgo aceptado: en los casos de contradicción podemos no coincidir con la referencia de Maisa.
  Lo asumimos porque es el comportamiento más seguro para Alberto y lo sabemos defender.

## Evidencia
Cifras de La Caja, ver [trampas.md](../trampas.md): 9 facturas de pedidos ya pagados, 3 de
proveedores inexistentes con el mismo IBAN, 13 con importe distinto, 1 reenvío, ~28 con notas.
