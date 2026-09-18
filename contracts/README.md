# Contratos entre módulos

La frontera entre las áreas. Cada módulo puede implementarse como quiera mientras respete esto.

```
ingesta ──factura_extraida──▶ decisión ──decision──▶ outcomes.jsonl
              ▲                    ▲
        (PDF, OCR, LLM)     fuentes: ERP + Excel
```

- `factura_extraida.schema.json`: lo que produce ingesta. Cada campo lleva `confianza` y `fuente` (trazabilidad).
- `decision.schema.json`: una línea de `outcomes.jsonl`. Solo `file_id` y `result` son obligatorios para la entrega; el resto es traza.
- `examples/*.ok.json`: ejemplos válidos. CI los valida contra el schema.

**Cambiar un contrato = PR propia + aviso al equipo** (ver AGENTS.md).
