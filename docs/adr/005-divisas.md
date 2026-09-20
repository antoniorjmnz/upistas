# ADR-005: Facturas en otra moneda

- **Estado**: aceptado
- **Fecha**: 2026-09-20
- **Issue**: #94

## Contexto
El lote 2 trae ocho facturas en dólares, libras, francos suizos, yenes y pesos (`e02`, `e09` a `e15`).
El pedido del maestro y el asiento del ERP van en euros, y la norma v3 compara el importe con el pedido
con una tolerancia de 0,01 €. Hasta ahora el lector tiraba el importe cuando la moneda no era el euro y
la factura salía a revisión como «divisa distinta de EUR», sin decirle a Alberto cuánto es ni si cuadra.
Comparar en bruto 2.450 USD con 2.254 € habría dado NO_PAGAR por importe, que es justo lo que no
queremos: la divisa no es un incumplimiento.

## Decisión
- La divisa es un dato más de la lectura (`campos.divisa`, con su texto de origen): sin marca o con
  «€»/«EUR», euros. Los importes se leen igual en cualquier moneda.
- En euros nada cambia: tolerancia de 0,01 € con el pedido e IVA contrastado.
- En otra moneda el importe nunca se compara en bruto con el pedido ni se contrasta el IVA, y la divisa
  por sí sola nunca es NO_PAGAR. La regla `R2_divisa` escala siempre con un motivo que dice la divisa, el
  importe leído, el pedido en euros y, si hay tipo de referencia, cuánto sale al cambio y si cuadra. El
  pago en divisa lo autoriza Alberto.
- Los tipos de referencia son una tabla fija en `normas/divisas.toml` (unidades de divisa por 1 €),
  acordada con Alberto para 2026 y sin internet; se cambia ahí, no en el código. «Cuadra al cambio» es
  una diferencia de como mucho el 0,5 % del pedido, el redondeo del tipo. Sin tipo para una divisa, se
  escala diciéndolo.
- NO_PAGAR solo con una prueba independiente de la divisa: IBAN distinto del maestro, NIF fuera del
  maestro, pedido inexistente o de otro proveedor. Por eso `R2_divisa` va a prioridad 340: por debajo de
  las reglas 1 y 2 (350) y por encima de la revisión por notas (300). Un pedido ya pagado en el ERP (100)
  sale en el motivo, pero la factura escala, igual que con las notas: escalar nunca autoriza un segundo pago.
- Un proveedor español facturando en divisa se escala igual, con el aviso «proveedor español facturando
  en USD». El país sale del formato del NIF (`pais_del_nif`), que la regla fiscal en curso reutilizará.

## Alternativas consideradas
- Escalar sin convertir, como hasta ahora: Alberto tendría que hacer la cuenta a mano con cada factura.
- Un tipo de cambio en vivo: la decisión dejaría de ser reproducible y el proceso necesitaría red.
- Convertir y aplicar la tolerancia de 0,01 €: el redondeo del tipo haría fallar facturas correctas.

## Consecuencias
- En el lote 2 las ocho facturas en divisa escalan con el importe al cambio en el motivo; `e11` (libras
  con IBAN distinto del maestro) sigue siendo NO_PAGAR por el IBAN, con la divisa como segunda causa.
  El lote 1 no cambia: todo va en euros.
- Cambiar un tipo o la tolerancia es editar `divisas.toml`; una norma nueva puede llevar otra tabla al lado.
- Riesgo aceptado: los tipos son de referencia, no los del día del pago. Por eso se escala, no se paga.
