# Cómo se decide cada factura

Un solo flujo para todo el equipo. Sale de la hoja de Alberto (`Norma_Pagos_v3`, seis reglas) y del
criterio acordado en [ADR-002](adr/002-criterio.md). El diagrama está en
[flujo_decision.drawio](flujo_decision.drawio) (se abre en app.diagrams.net) y la norma ejecutable en
`normas/v3.toml`. Si el código y este documento no dicen lo mismo, el que manda es el ADR y hay que
arreglar el otro.

## La idea en tres frases

Leer es siempre el primer paso y nunca decide nada. Decidir es determinista: reglas puras con tests,
sin IA. Solo hay tres salidas: PAGAR (cumple la norma), NO PAGAR (incumple una regla con datos leídos
con seguridad) y ESCALAR (lo mira Alberto, siempre con el motivo delante).

## El flujo, paso a paso

1. **Leer todo.** NIF, IBAN, número de pedido, importe, base, IVA, total, fecha, notas y texto oculto.
   Además la divisa y el país del NIF (ver «Lo que falta» abajo).
2. **¿Se ha leído lo necesario con seguridad?** Si no (escaneado ilegible, campo que no aparece, dos
   valores contradictorios), ESCALAR con el motivo «no se pudo leer». Un dato que no se pudo leer nunca
   prueba un incumplimiento.
3. **¿Está en euros?** Si no, ESCALAR: el pedido del maestro está en euros y no hay tipo de cambio
   pactado, así que el importe no se puede comparar. No es sospecha: la paga Alberto a mano si es
   legítima.
4. **Regla 1.** El NIF está en el maestro y el IBAN es igual al del maestro. Si no, NO PAGAR, aunque una
   nota diga que el proveedor ha cambiado de cuenta. Si el maestro no permite contrastarlo (ficha sin
   NIF o sin IBAN), ESCALAR.
5. **Regla 2.** El pedido existe, es de ese proveedor y el importe es igual con tolerancia de 0,01 €.
   Si no, NO PAGAR.
6. **Regla 4.** La fecha es válida y no futura. Una fecha imposible (31/02) leída con claridad es NO
   PAGAR; una fecha que no se pudo leer es ESCALAR (paso 2).
7. **Regla 3.** El IVA está bien calculado y el total es base más IVA (tolerancia 0,01 €). Si la suma no
   cuadra o la cuota no corresponde al tipo impreso, NO PAGAR. Si hay duda fiscal (sin tipo impreso,
   importes negativos, un tipo que no encaja con el país del NIF), ESCALAR.
8. **Regla 6.** Si trae notas relevantes, texto oculto, o Alberto la apuntó para revisar, ESCALAR. El
   texto de una factura nunca decide: ni autoriza ni bloquea un pago.
9. **Regla 5.** El pedido está PENDIENTE en el ERP y no se ha pagado ni aprobado antes. Si ya está
   pagado, aprobado en otro lote o es copia de una factura ya vista, NO PAGAR: nunca pagar dos veces.
   Si el ERP no tiene apunte, tiene apuntes que se contradicen, o Excel y ERP no coinciden sobre el
   pedido, ESCALAR.
10. **PAGAR** si ha pasado todo lo anterior.

## Cuando fallan varias reglas a la vez

Manda este orden, que es el de las prioridades de `normas/v3.toml`:

1. Lo que no se puede verificar (lectura, maestro, evaluación de la nota): ESCALAR.
2. Un incumplimiento probado (reglas 1, 2, 3 y 4): NO PAGAR, aunque haya nota o texto oculto.
3. Notas o texto oculto: ESCALAR, aunque el ERP diga que está pagada.
4. Pago previo o duplicado confirmado: NO PAGAR.

A igual nivel gana la más restrictiva: NO PAGAR antes que ESCALAR, ESCALAR antes que PAGAR. Escalar
nunca autoriza un segundo pago.

## Facturas extranjeras

Ser extranjera no es motivo de nada. Lo que cambia el tratamiento es el país del NIF y la divisa, no el
idioma (en el lote 2 hay una factura de un proveedor español en inglés y en dólares, y una francesa
que cobra IVA español).

- En euros y con todo cuadrando: PAGAR, sola.
- Regla 3 según el país del NIF: proveedor español, 21 %, 10 % o 4 % sobre la base; proveedor de la
  UE o de fuera, 0 % por inversión del sujeto pasivo o exención. IRPF, exenta o sujeto pasivo bien
  aplicados se pagan (ya está en el ADR-002).
- Proveedor extranjero cobrando IVA español: ESCALAR (duda fiscal), no NO PAGAR. Un contable pediría
  factura rectificada.
- En dólares o libras: ESCALAR (paso 3).
- NO PAGAR solo por lo probado: IBAN distinto, pedido inexistente o de otro proveedor, importe
  distinto, ya pagada.

## Lo que falta por hacer

- Leer la divisa como campo propio (hoy solo se reconoce el símbolo pegado al importe) y el país del
  NIF por su formato (español, de la UE, de fuera). Sin esos dos campos, los pasos 3 y 7 no se pueden
  aplicar tal cual.
- Cerrar la regla del IVA extranjero cuando tengamos la norma v4 delante: es muy probable que diga algo
  sobre proveedores extranjeros y divisas, y no queremos contradecirla.
- Repasar el flujo factura a factura (ver abajo) y corregir donde no cuadre.

## Cómo lo repasamos, factura a factura

1. Coge una factura del lote y sigue el flujo a mano con el PDF delante: qué dato falla y en qué paso.
2. Compara con lo que sale en la web (Facturas > detalle > «Por qué») o en `outputs/outcomes.jsonl`.
3. Si coinciden, siguiente. Si no coinciden, decide cuál de los dos está mal:
   - si el flujo tiene razón, es un bug o una lectura mal hecha: abre una issue con el fichero, el
     paso y lo que debería salir;
   - si el código tiene razón y el flujo no, es el flujo el que cambia: se edita este documento, el
     diagrama y, si hace falta, el ADR-002, en la misma PR.
4. Si la factura trae una trampa nueva, apúntala en [trampas.md](trampas.md).

Cifras de referencia con este flujo sobre el lote 1 (19 de septiembre por la noche): 423 se pagan, 34
no se pagan y 43 escalan (29 de ellas escaneados sin leer).
