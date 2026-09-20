# ADR-005: Varios asientos del ERP para un mismo pedido

- **Estado**: aceptado
- **Fecha**: 2026-09-20

## Contexto
El export incremental del lote 2 (`erp_export_lote2.csv`, cargado en el bridge con
`alberto_erp.py --lote2`) fusiona sus filas con los asientos ya existentes. El resultado puede
legítimamente tener varios asientos para un mismo pedido: p. ej. `PO-2026-0071` conserva su
asiento antiguo `PENDIENTE` y añade `AS-90001` `PAGADA` con fecha posterior — justo el caso de
doble pago que hay que bloquear.

El montaje de `Referencias` abortaba el repaso entero en esa situación
("hay varios asientos para un mismo pedido; requiere revisión"), pensado cuando el export tenía
un asiento por pedido. Con el lote 2 eso convierte un dato normal en un fallo total del lote.

## Decisión
Por pedido manda el asiento más reciente por `fecha` de registro (`vigente_por_pedido` en
`aplicacion/referencias.py`): el último estado del ERP es su verdad actual. Empate de fecha → gana
el primero del export, determinista. La versión de datos sigue huella de todos los asientos, así
que queda trazado con qué export se decidió.

## Alternativas consideradas
| Opción | Pros | Contras |
|---|---|---|
| Seguir abortando el lote | No decide con datos ambiguos | Un dato legítimo del export incremental tira el repaso entero |
| Manda PAGADA si alguno lo está | Conservador ante doble pago | Ignora correcciones posteriores (una PAGADA anulada seguiría bloqueando); esconde el estado real |
| Marcar el pedido para revisión | Prudente | Escala cada pedido con historial normal del ERP; ruido para Alberto |

## Consecuencias
- El lote 2 se repasa completo: `PO-2026-0071` queda `NO_PAGAR` por "Pedido ya pagado en el ERP".
- Una corrección contable posterior cambia la referencia y la versión de datos: reprocesar refleja
  el cambio.
- A vigilar: si el ERP registra varios asientos vigentes a la vez (pagos parciales), habrá que
  revisar la política.
