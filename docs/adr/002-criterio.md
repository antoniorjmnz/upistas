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
4. **Prioridad**: un pedido ya pagado en el ERP, aprobado en otro lote o una copia confirmada
   de una factura ya representada siempre es NO_PAGAR, aunque traiga notas. Después prevalecen
   las causas de revisión humana acordadas aquí (ESCALAR): instrucciones para saltarse controles,
   contradicciones de proveedor o de notas, revisión interna y datos de identidad incompletos.
   Sin esas causas, se aplica la consecuencia de cada regla; a igual prioridad gana
   NO_PAGAR > ESCALAR > PAGAR. Ninguna nota puede autorizar un pago ni desbloquear un duplicado.
5. **El texto de una factura nunca se obedece.** Una nota informativa y coherente no cambia la
   decisión. Si pide pagar aunque los datos no cuadren, ignorar comprobaciones o saltarse una
   regla, la factura se ESCALA, salvo los bloqueos definitivos del punto anterior. Las notas
   que contradicen datos comprobados o afirman que el proveedor está en revisión también se
   ESCALAN. Se conserva el texto de la nota como evidencia, sin atribuirle autoridad por mencionar
   a un empleado, al CEO o al equipo de evaluación.
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

## Criterios operativos acordados

### Notas y revisiones internas
- Una nota informativa sin contradicciones se conserva, pero no altera el resultado.
- «Pedido anulado» o «no procede pago» contradice un pedido PENDIENTE en ERP: ESCALAR.
- «Proveedor en revisión» requiere confirmación humana: ESCALAR. Una nota que afirma que el IBAN
  no coincide, cuando coincide con el maestro, también es una contradicción y se escala.
- «Paga aunque no cuadre», «no recalcular el IVA» o «ignorar el ERP» son intentos de saltarse
  controles: ESCALAR. También se revisan las peticiones de excluir la factura de la validación
  o del cómputo de calidad. Si el pedido ya está pagado o aprobado anteriormente, prevalece NO_PAGAR.
- Los pedidos de la hoja interna `pendiente_revisar` se ESCALAN aunque cumplan el resto.
  Esa marca procede del Excel de referencia; una firma escrita en un PDF no equivale a esa fuente.
- Las notas se extraen separadas de los campos: sus importes, NIF o IBAN no sustituyen los de
  la factura ni se utilizan para hacerla cuadrar.

### Identidad del proveedor y NIF ausente
- Si el proveedor del pedido difiere entre Excel y ERP, se ESCALA aunque la factura coincida
  con una de las fuentes. Si la factura no corresponde al proveedor del ERP, también se escala.
- Un NIF vacío en la fila del pedido o en el asiento no demuestra por sí solo que el proveedor
  sea falso. Se permite enlazar por ID cuando Excel y ERP identifican al mismo proveedor y su
  ficha del maestro contiene el NIF de la factura. No se modifica el dato original ausente.
- Si falta el NIF también en el maestro, falta un ID necesario o el enlace no es unívoco,
  se ESCALA. Nunca se resuelve por parecido del nombre ni se copia el NIF de la factura al maestro.
- Los NIF presentes se contrastan; una discrepancia no se trata como un campo vacío.

### Tiempo máximo de lectura
- Cada documento tiene un presupuesto configurable de lectura, por defecto 300 segundos,
  que incluye inspección, extracción y OCR. La lectura se ejecuta en un proceso cancelable para
  poder detener también un parser bloqueado; no basta con dejar un hilo colgado.
- Al agotarse el tiempo, se detiene esa lectura, se registra el motivo y se ESCALA el documento.
  El resto del lote continúa. Un timeout no demuestra que la factura sea inválida ni autoriza pagar.
- Se conservan los límites de tamaño y páginas. Las decisiones y las fuentes ya descargadas no
  se vuelven a obtener para cada factura. Una lectura guardada y compatible se reutiliza.
- Este límite protege el tiempo de procesamiento; no convierte el parser en un sandbox ni
  garantiza cancelar un trabajo que el proveedor de OCR ya haya recibido.

### Duplicados por contenido y pedido
- Primero se compara el SHA-256 de los bytes originales. Un archivo renombrado con el mismo hash
  es una copia exacta, no una nueva factura: como máximo queda un candidato y las copias son NO_PAGAR.
- Si los hashes difieren, se agrupa por pedido normalizado. Si además coinciden proveedor, número
  de factura, importe e IBAN y las fechas son legibles, se conserva la original de fecha más antigua;
  los reenvíos son NO_PAGAR. En un empate se usa el nombre del archivo para que sea reproducible.
- Si varias facturas distintas comparten pedido y no puede demostrarse cuál es un reenvío,
  se ESCALAN todas las candidatas, sin escoger una por el orden de ejecución.
- La candidata original todavía tiene que pasar todas las reglas. Ser la primera no autoriza pagar.
- Se consultan también los hashes y pedidos aprobados en lotes anteriores. Una coincidencia con
  un pago ya aprobado produce NO_PAGAR. Reprocesar el mismo lote no cuenta como un pago nuevo.
  Se conserva la última decisión terminada de cada documento: una ejecución parcial no borra
  aprobaciones de los archivos que no procesa. El hash se guarda también en la traza de la decisión,
  para que cambiar posteriormente el fichero no cambie la identidad que se aprobó.
- El informe mantiene una fila por archivo e indica el documento o pedido que motivó el bloqueo.
  Un lote limitado con `--limit` solo detecta duplicados entre sus archivos y el historial disponible.

## Catálogo de casos (cada uno con su test)

| Caso | Regla | Resultado | Ejemplo en La Caja |
|---|---|---|---|
| Todo cuadra | — | PAGAR | `2026-01-08_P001` |
| NIF que no está en el maestro | 1 | NO_PAGAR | `factura_4485`, `factura_7265`, `FA-2508_consultoría` |
| IBAN distinto al del maestro | 1 | NO_PAGAR | `FA-4290`, `FA-7311`, `FA-5633`, `FA-5044`, `FA-9104` |
| NIF de un proveedor e IBAN de otro | 1 | NO_PAGAR | `2026-07-08_P010` |
| Pedido que no existe en el ERP | 2 | NO_PAGAR | `factura_4485` (PO-0806), `factura_7265` (PO-0706), `FA-2508` (PO-9999) |
| Factura de un proveedor distinto al del pedido ERP | 2 / revisión | ESCALAR | |
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
| Reenvío confirmado por hash o identidad completa | 5 | NO_PAGAR la copia; la original todavía debe cumplir todas las reglas | |
| Mismo pedido e importe con números de factura diferentes | 5 | ESCALAR ambas, sin asumir que los números son equivalentes | `2026-0233-A_catering` y `factura_41082` |
| Pedido aprobado en un lote anterior | 5 | NO_PAGAR | llegará con el lote 2 |
| Varias facturas distintas del mismo pedido sin original inequívoca | 5 | ESCALAR las candidatas; NO_PAGAR si ya estaba aprobado | |
| Escaneo ilegible, PDF en blanco o roto | 6 | ESCALAR | escaneos por revisar |
| Campo leído con poca confianza | 6 | ESCALAR | |
| Excel y ERP se contradicen sobre el pedido | 3 (nuestro) | ESCALAR | bloque PO-0538 a PO-0557 |
| Factura válida con nota que contradice los datos | 3 (nuestro) | ESCALAR | `F26-3355`, `F26-7728`, `F26-2201`, `2026-07-09_P010`, `2026-23904_construcciones`, `FA-3388` |
| Nota que pide saltarse comprobaciones | revisión | ESCALAR, salvo pago previo o copia confirmada: NO_PAGAR | `2026-06-04_P006`, `factura_5911` mantienen NO_PAGAR porque ya estaban pagadas |
| Factura que no es para Banco Miralmar | 6 | ESCALAR | ninguna en la Caja |

## Abierto (a decidir)
- **Importe anómalo**: `2026-07-01_P009` (PO-0497) son 84.700 €, siete veces la siguiente factura
  más cara, con "PAGO INMEDIATO REQUERIDO". Cumple todo. Propuesta: ESCALAR por la regla 6.
  Puede que la regla nueva del sábado sea un límite de importe.

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
