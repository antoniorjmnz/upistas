# Arquitectura

Arquitectura hexagonal (puertos y adaptadores). El dominio no sabe nada de PDFs, HTTP, LLMs,
DBOS ni Django; todo eso se enchufa desde fuera. Las fronteras las vigila `lint-imports` en la CI.

```mermaid
flowchart LR
  subgraph infra[infra]
    CLI[cli] --> P[pipeline DBOS]
    C[contenedor]
  end
  subgraph ad[adaptadores]
    L1[lector pdf_texto]
    L2[lector LLM texto]
    L3[lector LLM visión]
    X[Excel de Alberto]
    E[ERP bridge 2009]
  end
  subgraph app[aplicacion]
    U[procesar: leer → decidir]
    M[mapeo contratos ↔ dominio]
  end
  subgraph dom[dominio]
    N[norma vN.toml]
    R[reglas R1..R5]
    I[importes y fechas]
  end
  P --> U
  C -. monta .-> ad
  U --> N --> R
  U -. puertos .-> ad
```

| Capa | Carpeta | Puede importar | Qué hay |
|---|---|---|---|
| Dominio | `src/upistas/dominio/` | nada del proyecto | Modelos, reglas, norma, parseo de importes. Funciones puras. |
| Puertos | `src/upistas/puertos.py` | dominio, contratos | Interfaces: `LectorDocumento`, `FuenteMaestro`, `FuenteERP`, `ModeloLenguaje`. |
| Aplicación | `src/upistas/aplicacion/` | dominio, puertos | Casos de uso. Reciben los adaptadores ya montados. |
| Adaptadores | `src/upistas/adaptadores/` | todo lo anterior | Implementaciones: PDF, Excel, ERP, Helmcode... |
| Infra | `src/upistas/infra/` | todo | DBOS, montaje (`contenedor.py`), CLI. |
| Web | `web/` | aplicación e infra | Django: panel y bandeja de revisión. |

Los datos cruzan los bordes como **contratos** (`contracts/*.schema.json`, modelos Pydantic
generados) y dentro del dominio como dataclasses propias.

## Cómo añadir cosas

**Una regla de pago** → archivo nuevo en `dominio/reglas/` con `@regla("R6_lo_que_sea")` y
activarla en `normas/vN.toml`. Test en `tests/unit/`.

**Una norma nueva (v4)** → copiar `normas/v3.toml` a `v4.toml` y cambiar reglas o consecuencias.
Reprocesar: `uv run upistas run --norma v4`. Si la v4 trae una regla nueva, además el punto anterior.

**Un tipo de documento nuevo (emails, Excel de facturas...)** → un lector en
`adaptadores/lectores/` que implemente `LectorDocumento` y añadirlo a `contenedor.lectores()`.
Dominio y reglas no cambian.

**Otro proveedor de LLM o de respaldo** → un adaptador de `ModeloLenguaje` y elegirlo en
`contenedor.py` o por `.env`.

**Otra fuente de datos (otro ERP, una base de datos)** → un adaptador de `FuenteERP` o
`FuenteMaestro` y cambiarlo en `contenedor.py`.

**Una pantalla del panel** → vista en `web/`, que llama a la aplicación; nunca a adaptadores.

## Reglas de oro
- Lógica de negocio solo en `dominio/`. Si un `if` decide algo de pagos fuera de ahí, está mal ubicado.
- Los `@DBOS.step` solo orquestan: toda E/S que no deba repetirse tras una caída va en un step.
- `contenedor.py` es el único sitio que conoce las clases concretas de los adaptadores.
- Tests unitarios sin red ni disco; los de integración usan fuentes en memoria (`adaptadores/fuentes/memoria.py`).
