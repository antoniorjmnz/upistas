# albertitos_plan (provisional)

Esqueleto del PDF de la entrega. La idea es que cada punto sea una o dos frases con un dato detrás;
lo que no tenga dato medido va marcado como estimación. Iterad encima, borrad lo que no aplique y
cuando esté cerrado se genera el PDF desde aquí y desde `docs/adr/`.

Lo que puntúa (110): producto, arquitectura y ADRs 35 · escala y coste 25 · trazabilidad 20 ·
resiliencia 10 · calidad 10 · bonus 10. El PDF tiene dos secciones obligatorias: Arquitectura y
ADRs / trade-offs (de 2 a 5). Sin PDF o con uno pobre se pierden los 35.

## 1. Arquitectura

### 1.1 El problema y para quién
- Alberto heredó la empresa, no sabe de informática y recibe facturas en PDF (500 + 40) que tiene
  que cruzar con un Excel caótico y un ERP de 2009 para decidir PAGAR / NO_PAGAR / ESCALAR.
- Los datos mienten: pedidos ya pagados, duplicados, proveedores falsos, IBAN con caracteres
  invisibles y unas 28 facturas con texto que intenta manipular la decisión.
- Lo que Alberto necesita: una bandeja donde solo mire lo dudoso, con el motivo en sus palabras.

### 1.2 El formato y por qué
- Pipeline que corre solo (`upistas run`) + web Django con Resumen, Facturas con traza, Para revisar
  y Ejecuciones. Ni consola ni jerga para Alberto.
- Descartado: CLI sola (Alberto no la usaría), agente conversacional que decide (no auditable),
  app grande con API + front (no mejora lo que puntúa). El formato es una decisión, no un default.

### 1.3 Componentes
- Hexagonal: dominio (reglas puras y norma) → aplicación (leer, decidir, sincronizar) → adaptadores
  (lectores PDF/OCR, Excel, ERP HTTP, copia del ERP, Helmcode, persistencia Django) → infra (DBOS,
  contenedor, CLI) → web. Diagrama en `docs/arquitectura.md`.
- Los datos cruzan las capas como contratos (`contracts/*.schema.json`). `lint-imports` bloquea
  la CI si una capa importa lo que no debe: "el LLM no decide" es una capa, no una frase.

### 1.4 Flujo de datos y estado
- PDF → inspeccionar (tipo, huella sha256, alertas: fichero incrustado, texto oculto) → leer
  (texto determinista o visión LLM; duradero y cacheado por huella) → decidir (reglas + norma
  vN.toml; barato, se repite entero) → outcome con traza por regla.
- Cada ejecución guarda `version_datos`: huella del ERP, del maestro y versión de la norma. Se sabe
  con qué datos se tomó cada decisión y se reprocesa solo lo afectado.
- Nunca se paga dos veces: hash del PDF, pedido y lista propia de pedidos aprobados en lotes
  anteriores, porque el ERP es de solo lectura y no se entera de lo que decidimos.

### 1.5 Reparto entre agentes, modelos y personas
- Modelos: `qwen3.6` (visión) solo para los 29 escaneos; `glm5.3` (texto) solo para decir si una
  nota es relevante. Ninguno emite PAGAR/NO_PAGAR/ESCALAR.
- Reglas deterministas: deciden todo. Prioridades en el toml, no en el código.
- Personas: Alberto mira la bandeja de revisión; Sonia (IVA) e IT (migración) detrás de los
  escalados que lo piden.
- Equipo: 4 personas con 4 agentes, una issue por tarea, CODEOWNERS por área, AGENTS.md. La
  arquitectura se diseñó para trabajar en paralelo sin pisarse.

### 1.6 Cómo se observan y recuperan los fallos
- Observar: historial de cada sincronización con el ERP (peticiones, reintentos, 429, relogins),
  traza por paso de cada factura, tokens y coste por lectura, lecturas fallidas con motivo.
- Recuperar: DBOS retoma cada factura en su último paso tras una caída, sin repetir la llamada al
  LLM (probado: proceso matado entre leer y decidir, una sola lectura). ERP caído → última copia
  buena y aviso. LLM caído o timeout de lectura (300 s) → ESCALAR con motivo, el resto del lote sigue.
- Degradación honesta: si no se puede leer o verificar, se escala; nunca se inventa un dato.

### 1.7 Escala y coste (mediciones separadas de estimaciones)
- Medido: ERP completo (516 asientos) en 3,9-4,0 s con 2-3 ORA-00600 absorbidos; 500 facturas
  recorridas de punta a punta con pasos vacíos en 35,7 s (SQLite, 1 proceso). PENDIENTE: tiempo real
  de lectura por factura (texto y OCR), tiempo de decidir 540 facturas sin releer, tokens por escaneo.
- Cuello de botella: la espera (LLM, ERP, disco), no la CPU. Más throughput = más workers sobre
  Postgres, sin cambiar código. Límite duro externo: 10 peticiones/s del ERP.
- Coste: Helmcode tarifa plana → coste marginal por factura ≈ 0 €. Fórmula: coste = plana/mes +
  tokens_visión × precio si se usa respaldo frontier. PENDIENTE: número con el lote 2.
- Estimación (marcarla como tal): capacidad por hora con N workers y qué se rompe primero.

### 1.8 Qué cambiaría con emails, imágenes o Excel
- Un lector nuevo en `adaptadores/lectores/` o una fuente en `adaptadores/fuentes/` con el mismo
  contrato. Dominio, reglas y web no cambian. Es la recompensa de la hexagonal; decirlo antes de
  que lo pregunten.

### 1.9 Límites (decirlos nosotros antes de que los busquen)
- No escribe en el ERP. No convierte divisas. No obedece ni interpreta autoridad en el texto de una
  factura. No decide sobre casos que la norma no cubre: los escala.
- La copia del ERP puede quedarse vieja si nadie sincroniza (se ve la fecha en la web).
- Escalar mucho tiene coste para Alberto: cuántas facturas escalamos y por qué, con número.

## 2. ADRs / trade-offs (máximo 5 en el PDF)

Cada uno con contexto, alternativas, decisión, consecuencias (también las que duelen) y evidencia.
Los completos están en `docs/adr/`.

1. **El LLM extrae, las reglas deciden.** La IA convierte documentos en datos y clasifica notas;
   PAGAR/NO_PAGAR/ESCALAR lo produce código determinista y trazable. Cubre los PDFs maliciosos
   (notas, fichero incrustado, texto oculto). Falta escribirlo como ADR propio; hoy está repartido
   entre 001 y 002.
2. **Leer y decidir son fases separadas; la norma es un fichero.** Leer es caro y se cachea por
   huella; decidir es barato y se repite entero con `normas/vN.toml`. Es lo que hace posible la v4,
   el lote 2 y el dato del domingo sin releer ni tocar código. Falta escribirlo (ADR-005).
3. **Fuentes de referencia versionadas por contenido: copia del ERP y maestro propio.** Un solo
   conector descarga el ERP entero, absorbe sus fallos y guarda una copia versionada de solo
   lectura; el maestro sale del Excel a tablas propias con validación. Fusión de 003 y 004.
4. **Stack: DBOS + Django/HTMX + Helmcode.** Ejecución duradera como librería porque el cuello es
   la espera y lo que importa es qué pasa a mitad; web simple para Alberto; modelos abiertos en la
   UE a tarifa plana. Riesgo aceptado: DBOS es joven. Es el ADR-001.
5. **Criterio de decisión y escalera de prioridades.** Incumplimiento probado → NO_PAGAR; duda,
   dato ilegible o contradicción → ESCALAR; el texto de la factura nunca se obedece. Prioridades
   400/350/300/100/50 en el toml. Resumen del ADR-002, con dos facturas reales seguidas de punta a punta.

## 3. Pendientes para cerrar el PDF
- Escribir ADR-005 y el ADR del principio "LLM extrae, reglas deciden".
- Fusionar 003 y 004 o decidir cuál se queda fuera del PDF.
- Rellenar los PENDIENTE de 1.7 con números del lote 2.
- Añadir sección de evidencia a 002 y 004.
- Elegir las dos facturas de ejemplo para la traza (una PAGAR limpia y una ESCALAR con nota).
- Bonus, si lo hay: una frase de qué es y cómo se enseña en la demo.
