# El reto: qué piden y cómo se evalúa

Resumen de todo lo oficial: el README del repo de Alberto, la web del hackathon y lo que nos ha
respondido el staff. Si algo de aquí contradice a la fuente, manda la fuente.

## Qué hay que construir
Un sistema que procese las facturas de Alberto (PDF, algunas escaneadas), las cruce con su Excel y su
ERP de 2009, y decida para cada una **PAGAR**, **NO_PAGAR** o **ESCALAR**. El formato es libre (CLI,
backend, web, herramienta para agentes...), pero hay que defender por qué es el adecuado.

> "Un backend pequeño y bien razonado puede superar a una aplicación grande sin criterio."
> No se puntúa el tamaño.

**Respuesta del staff**: "El objetivo del reto es clasificar las facturas de forma que puedas pagar,
no pagar o escalarlas con la información que tienes. Parte de la solución es definir e implementar
un criterio para casos como este." Es decir: no nos van a dar las respuestas de los casos dudosos;
el criterio es nuestro y se evalúa. Está en [adr/002-criterio.md](adr/002-criterio.md) cuando exista.

## Qué se entrega (domingo 10:30)
Un repo público **aparte**, con exactamente estos tres archivos en la raíz:
- `outcomes.jsonl`: una línea por factura del lote 1. Obligatorio `file_id` y `result`; se pueden añadir campos de traza.
- `outcomes_lote2.jsonl`: lo mismo para el lote 2.
- `albertitos_plan.pdf`: dos secciones, **Arquitectura** (componentes, flujo de datos y estado, reparto entre agentes, modelos y personas, cómo se observan y recuperan los fallos) y **ADRs / trade-offs** (de 2 a 5 decisiones con contexto, alternativas, decisión, consecuencias y evidencia).

Nada de código, credenciales ni ejecutables en ese repo. No ejecutan nuestro código.

## Validación (para optar al premio)
Binaria y sin puntos: exactamente un resultado por archivo en los dos lotes, y cada `result` tiene
que coincidir con **uno de** los resultados esperados de su referencia privada (en algún caso puede
valer más de uno). Si no se supera, se puede defender igual pero sin premio.

## Calendario
- Viernes 19:00: repo con La Caja (500 facturas, Excel, ERP).
- Sábado 18:00: `lote-2-sorpresa-v3.2.zip` con 40 facturas más y una regla nueva. **Comprobar los hashes publicados en el canal.**
- Domingo: pueden cambiar un dato de La Caja. Conocen el efecto esperado para ver que la demo es real.
- Domingo 10:30: cierre de entrega. Luego, defensa.

## Rúbrica (110 puntos)
| Criterio | Puntos | Qué miran |
|---|---|---|
| Producto, arquitectura y ADRs | 35 | Problema, formato, decisiones, alternativas y trade-offs. Sin PDF o con uno pobre se pierden. |
| Escalabilidad y coste | 25 | Capacidad, límites, cálculo económico, evolución. **Mediciones separadas de estimaciones.** |
| Trazabilidad y observabilidad | 20 | Decisiones auditables, estado, señales operativas. |
| Resiliencia y recuperación | 10 | Fallos del proveedor, estado, degradación, recuperación. |
| Calidad de ejecución | 10 | Claro, proporcionado, agradable de operar. |
| Bonus | +10 | Una mejora para Alberto, implementada y demostrada. |

Desempate: escalabilidad, luego resiliencia, luego bonus.

**El bonus no cuenta** si es una propuesta, una maqueta, un cambio cosmético, algo ya necesario para
el flujo principal o el lote del sábado.

## La defensa: 10 minutos con el mismo guion para todos
1. **Demo y contexto (2 min)**: la solución funcionando y el problema concreto que resuelve. Si hay bonus, se enseña aquí.
2. **Arquitectura y ADRs (2 min)**: apoyados en el PDF. Formato, arquitectura, reparto entre agentes, modelos y personas, decisiones.
3. **Trazabilidad, escala y coste (4 min)**: seguir una decisión real, enseñar las señales operativas, capacidad, hardware, fórmula de coste y supuestos. Qué cambiaría con emails, imágenes o Excel.
4. **Resiliencia y preguntas (2 min)**: explicar o demostrar un timeout, rate limit, respuesta inválida o caída del proveedor. Qué se conserva, cómo se evitan duplicados y cómo se recupera.

Nos pueden preguntar por cualquier decisión, alternativa o trade-off que esté en el PDF.

## Qué no piden
Ni una interfaz concreta, ni un stack concreto, ni un benchmark de OCR, ni promesas abstractas de
escala, ni alta disponibilidad perfecta. Sí una estrategia honesta cuando un proveedor falla.

## Lo que dijeron los mentores
- *"Albertito es un tío que ha heredado la empresa del padre y no tiene ni idea"* de informática. Todo tiene que ser fácil para él.
- Van a probar el sistema con PDFs raros y maliciosos: inyección de código, metadatos corruptos, payloads, prompt injection, PDFs en blanco, escaneos ilegibles, incompletos...
- Se puede pedir a los mentores una consulta de diseño o un simulacro breve de defensa.

## ERP local
En el repo de Alberto: `make help`, `make erp` (dejar esa terminal abierta; escucha en
`http://127.0.0.1:8009`), `make erp-status`, `make erp-login`. `make erp-fast` quita la latencia para
tests. El sábado: `make erp-lote2`. Detalles y trampas en [trampas.md](trampas.md).
