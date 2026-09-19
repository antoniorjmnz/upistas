# Empieza aquí

Todo lo que necesitas para ponerte a trabajar en upistas sin preguntar. Léelo una vez entero (10 min).

Más a fondo: [reto.md](reto.md) (lo que piden, la rúbrica y la defensa) y [trampas.md](trampas.md) (todo lo raro que hay en los datos).

## El reto en una frase
Alberto recibe facturas en PDF y tiene que decidir cuáles **PAGAR**, cuáles **NO_PAGAR** y cuáles
**ESCALAR** a una persona, cruzándolas con un Excel caótico y un ERP de 2009. Nosotros construimos
el sistema que lo hace por él y lo defendemos ante el tribunal de Maisa.

## Quién es Alberto
Palabras de los mentores: *"Albertito es un tío que ha heredado la empresa del padre y no tiene ni idea"*
de informática. Todo lo que hagamos tiene que ser fácil para él: nada de consolas, jerga ni pasos manuales.

## Calendario
| Cuándo | Qué | Milestone |
|---|---|---|
| Sáb 19 · 18:00 | Llega el lote 2 (+40 facturas), actualización del ERP y norma v4 | **Lote 1** tiene que estar listo |
| Sáb noche | Lote 2 aplicado y todo lo de la demo | **Lote 2 y demo** |
| Dom 20 · 10:30 | Cierre de entrega | **Entrega** |
| Dom 20 | Defensa de 10 minutos | |

El domingo, además, cambiarán un dato de La Caja para comprobar que la demo es real.

## Qué se entrega
Un repo público **aparte** con solo `outcomes.jsonl`, `outcomes_lote2.jsonl` y `albertitos_plan.pdf`.
Para optar al premio tiene que haber exactamente un resultado por factura y coincidir con la
referencia privada de Maisa. El código se enseña en la defensa, no se entrega.

Rúbrica (110 puntos): producto, arquitectura y ADRs 35 · escala y coste 25 · trazabilidad 20 ·
resiliencia 10 · calidad 10 · bonus 10. El bonus es una mejora extra para Alberto que no sea
necesaria para el flujo principal.

## Los datos (resumen de [analisis-caja.md](analisis-caja.md))
- **Facturas**: 500 PDF en unas 10 plantillas distintas. 471 tienen texto; 29 son escaneos (hace falta IA con visión). Alguno está corrupto.
- **Excel** `FINAL_v7_DEFINITIVO_ahorasi.xlsx`: proveedores, pedidos y, escondida, la hoja **`Norma_Pagos_v3`** con las reglas. El resto de hojas es basura.
- **ERP**: se arranca en local (`make erp` en el repo oficial). Lento, con errores aleatorios que hay que reintentar y sesiones que caducan. Es la referencia oficial cuando no coincide con el Excel.
- **Trampas**: pedidos ya pagados, facturas duplicadas, proveedores falsos, importes que no cuadran, IBAN con caracteres invisibles y unas 28 facturas con notas que intentan manipular la decisión. Todas en [trampas.md](trampas.md).

## La norma v3
1. NIF en el maestro y el IBAN de la factura igual al del maestro.
2. El pedido existe, es de ese proveedor y el importe coincide (±0,01 €).
3. IVA bien calculado y total = base + IVA (±0,01 €).
4. Fecha válida y no futura.
5. Pedido PENDIENTE en el ERP; nunca pagar dos veces el mismo pedido.
6. Ante la duda, ESCALAR con motivo.

## Lo que hemos decidido
- **El LLM solo lee; las reglas deciden.** La IA convierte documentos en datos. PAGAR/NO_PAGAR/ESCALAR lo decide código determinista y auditable.
- **Stack**: Python + DBOS + Django + HTMX. Por qué y alternativas en [ADR-001](adr/001-stack.md).
- **IA**: Helmcode (servidores en la UE, tarifa plana). `qwen3.6` para escaneos, `glm5.3` para texto. La clave va en tu `.env`; pídela por privado.
- **La norma es un fichero** (`normas/v3.toml`). La v4 del sábado será otro fichero.
- **Cada factura es un workflow duradero**: si el proceso se cae, al arrancar sigue donde iba sin repetir nada.

## Cómo está el código
Capas separadas (arquitectura hexagonal). Detalle y recetas de "cómo añadir X" en
[arquitectura.md](arquitectura.md). Lo mínimo:

| Quiero... | Toco... |
|---|---|
| Añadir o cambiar una regla de pago | `src/upistas/dominio/reglas/` + `normas/v3.toml` |
| Leer un tipo de documento nuevo o mejorar la lectura | `src/upistas/adaptadores/lectores/` |
| Conectar Excel, ERP u otra fuente | `src/upistas/adaptadores/fuentes/` |
| Cambiar qué pieza se usa | `src/upistas/infra/contenedor.py` |
| Hacer pantallas para Alberto | `web/` |
| Cambiar el formato de los datos entre módulos | `contracts/` (PR aparte, avisando) |

## Estado actual
Funciona de punta a punta: sincroniza el ERP (copia local versionada, ver [ADR-003](adr/003-erp-copia-local.md)),
recorre las 500 facturas y genera `outputs/outcomes.jsonl`. Pero todavía **todas salen ESCALAR**,
porque faltan la lectura de PDFs, el Excel y casi todas las reglas.
Eso es el milestone **Lote 1**. Lo que hay pendiente está en el
[tablero](https://github.com/users/antoniorjmnz/projects/2), agrupado por milestone.

## Cómo trabajar
1. Coge una tarjeta de **To do** del tablero y asígnatela. Con Claude Code: `/tarea 25`.
2. Trabaja en tu rama, con commits de una línea: `feat(fuentes): cargar el Excel (#25)`.
3. `uv run python scripts/check.py` en verde y abre la PR (`/pr` en Claude Code). Se acepta sola cuando la CI pasa y alguien la fusiona.

Reglas completas en [AGENTS.md](../AGENTS.md) y chuleta de comandos en [CONTRIBUTING.md](../CONTRIBUTING.md).

## Arrancar en tu PC
```bash
git clone https://github.com/antoniorjmnz/upistas && cd upistas
git clone https://github.com/ikurotime/500-sombras-de-alberto ../caja
cp .env.example .env        # y pon HELMCODE_API_KEY
sh scripts/setup.sh         # formato de commits
uv sync --extra dev         # instala todo (necesitas uv: https://docs.astral.sh/uv/)
uv run pytest               # tiene que salir todo en verde

# en otra terminal, el ERP de Alberto (déjala abierta; sin make en Windows):
python ../caja/alberto_erp.py

uv run upistas erp sync     # copia local del ERP (516 asientos, ~4 s)
uv run upistas run --limit 20
```
