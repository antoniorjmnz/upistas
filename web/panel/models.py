"""Nuestra base de datos. El ERP de Alberto nunca se toca: aquí guardamos una copia versionada
de sus asientos, cada lectura de cada documento, cada ejecución y cada decisión con su traza."""
from django.db import models

from upistas.dominio.importes import normaliza_iban

# --- Copia del ERP ---------------------------------------------------------------------------


class VersionERP(models.Model):
    """Una foto del contenido del ERP. Misma foto = misma versión (huella del contenido)."""

    version = models.CharField(primary_key=True, max_length=16)
    creada = models.DateTimeField()
    n_asientos = models.PositiveIntegerField()
    lote2_cargado = models.BooleanField(default=False)

    class Meta:
        ordering = ["-creada"]
        verbose_name = "versión del ERP"
        verbose_name_plural = "versiones del ERP"

    def __str__(self) -> str:
        return f"{self.version} ({self.n_asientos} asientos)"


class AsientoERP(models.Model):
    version = models.ForeignKey(VersionERP, on_delete=models.CASCADE, related_name="asientos")
    asiento_id = models.CharField(max_length=20)
    pedido = models.CharField(max_length=20, db_index=True)
    proveedor_id = models.CharField(max_length=10)
    nif = models.CharField(max_length=12, blank=True)
    importe = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=12)

    class Meta:
        ordering = ["asiento_id"]
        constraints = [models.UniqueConstraint(fields=["version", "asiento_id"], name="asiento_unico_por_version")]
        verbose_name = "asiento del ERP"
        verbose_name_plural = "asientos del ERP"

    def __str__(self) -> str:
        return f"{self.asiento_id} · {self.pedido} · {self.estado}"


class SincronizacionERP(models.Model):
    """Cada vez que hablamos con el ERP, haya ido bien o mal."""

    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    ok = models.BooleanField()
    version = models.ForeignKey(VersionERP, null=True, blank=True, on_delete=models.SET_NULL, related_name="sincronizaciones")
    n_asientos = models.PositiveIntegerField(default=0)
    lote2_cargado = models.BooleanField(default=False)
    peticiones = models.PositiveIntegerField(default=0)
    reintentos_ora = models.PositiveIntegerField(default=0)
    esperas_429 = models.PositiveIntegerField(default=0)
    relogins = models.PositiveIntegerField(default=0)
    errores_red = models.PositiveIntegerField(default=0)
    segundos = models.FloatField(default=0)
    error = models.TextField(blank=True)
    nuevos = models.PositiveIntegerField(default=0)
    modificados = models.PositiveIntegerField(default=0)
    eliminados = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-inicio", "-id"]
        verbose_name = "sincronización con el ERP"
        verbose_name_plural = "sincronizaciones con el ERP"

    @property
    def hay_cambios(self) -> bool:
        return bool(self.nuevos or self.modificados or self.eliminados)


# --- Documentos y lecturas ------------------------------------------------------------------


class Documento(models.Model):
    """Un fichero de un lote. La huella identifica el contenido aunque cambie de nombre."""

    lote = models.CharField(max_length=40, db_index=True)
    file_id = models.CharField(max_length=255)
    ruta = models.TextField()
    sha256 = models.CharField(max_length=64, db_index=True)
    bytes = models.PositiveIntegerField(default=0)
    tipo = models.CharField(max_length=12)  # texto | escaneado | blanco | roto | cifrado | otro
    paginas = models.PositiveIntegerField(default=0)
    alertas = models.JSONField(default=list, blank=True)
    primera_vez = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["lote", "file_id"]
        constraints = [models.UniqueConstraint(fields=["lote", "file_id"], name="documento_unico_por_lote")]

    def __str__(self) -> str:
        return f"{self.lote}/{self.file_id}"


class Lectura(models.Model):
    """Qué se sacó de un contenido (por huella) y cómo. Una por contenido: no se lee dos veces lo mismo."""

    sha256 = models.CharField(max_length=64, unique=True)
    file_id = models.CharField(max_length=255)  # el primer nombre con el que se vio
    lote = models.CharField(max_length=40)
    ok = models.BooleanField()
    lector = models.CharField(max_length=40, blank=True)
    metodo = models.CharField(max_length=20)  # texto_determinista | texto_llm | vision_llm | ninguno
    extraida = models.JSONField(null=True, blank=True)  # el contrato factura_extraida
    intentos = models.JSONField(default=list, blank=True)  # [(lector, por qué no pudo)]
    segundos = models.FloatField(default=0)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    coste_eur = models.FloatField(default=0)
    modelo = models.CharField(max_length=60, blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creada"]

    def __str__(self) -> str:
        return f"{self.file_id} · {self.metodo}"


# --- Ejecuciones y decisiones ---------------------------------------------------------------


class Ejecucion(models.Model):
    """Una pasada completa por un lote con una norma y una versión de los datos."""

    lote = models.CharField(max_length=40, db_index=True)
    norma = models.CharField(max_length=20)
    version_erp = models.CharField(max_length=16, blank=True)
    version_excel = models.CharField(max_length=16, blank=True)
    inicio = models.DateTimeField()
    fin = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=12, default="en_curso")  # en_curso | terminada | interrumpida
    hardware = models.JSONField(default=dict, blank=True)
    resumen = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-inicio", "-id"]
        verbose_name_plural = "ejecuciones"

    @property
    def version_datos(self) -> str:
        return f"{self.version_erp}+{self.version_excel}"

    def __str__(self) -> str:
        return f"{self.lote} · {self.norma} · {self.inicio:%d/%m %H:%M} · {self.estado}"


class Decision(models.Model):
    ejecucion = models.ForeignKey(Ejecucion, on_delete=models.CASCADE, related_name="decisiones")
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, related_name="decisiones")
    resultado = models.CharField(max_length=10, db_index=True)  # PAGAR | NO_PAGAR | ESCALAR
    motivo = models.TextField(blank=True)
    pedido = models.CharField(max_length=20, blank=True, db_index=True)
    metodo = models.CharField(max_length=20, blank=True)
    outcome = models.JSONField(default=dict)  # la línea de outcomes.jsonl, con reglas y alertas
    notas = models.JSONField(default=list, blank=True)
    alertas = models.JSONField(default=list, blank=True)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["documento__file_id"]
        constraints = [models.UniqueConstraint(fields=["ejecucion", "documento"], name="una_decision_por_documento_y_ejecucion")]
        verbose_name_plural = "decisiones"

    def __str__(self) -> str:
        return f"{self.documento.file_id}: {self.resultado}"


class RevisionHumana(models.Model):
    """Lo que Alberto (o quien revise) decide sobre una factura escalada. El original no se toca."""

    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, related_name="revisiones")
    decision = models.ForeignKey(Decision, null=True, blank=True, on_delete=models.SET_NULL, related_name="revisiones")
    quien = models.CharField(max_length=150)
    cuando = models.DateTimeField(auto_now_add=True)
    resultado = models.CharField(max_length=10)  # PAGAR | NO_PAGAR
    comentario = models.TextField(blank=True)

    class Meta:
        ordering = ["-cuando"]
        verbose_name_plural = "revisiones humanas"


# --- Maestro: los proveedores y pedidos de Alberto, mantenidos desde la web -------------------


class Proveedor(models.Model):
    """A quién se le paga. Antes vivía en la hoja Proveedores del Excel.

    `codigo` es el nombre que el ERP le da al proveedor en sus asientos (`AsientoERP.proveedor_id`):
    aunque Alberto no lo mire nunca, sin él no se puede cruzar un pedido con su asiento.
    `activo` es informativo (con quién se sigue trabajando); no cambia ninguna decisión.
    """

    codigo = models.CharField(max_length=10, unique=True)  # P001, P002...
    nombre = models.CharField(max_length=200)
    nif = models.CharField(max_length=24, unique=True)
    iban = models.CharField(max_length=34)
    ciudad = models.CharField(max_length=80, blank=True)
    condiciones_dias = models.PositiveSmallIntegerField(null=True, blank=True)  # 30, 60... días para pagar
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "proveedores"

    def save(self, *args, **kwargs):
        # Se guardan ya comparables con lo que se lee de una factura: sin espacios y en mayúsculas.
        self.nif = (self.nif or "").replace(" ", "").upper()
        self.iban = normaliza_iban(self.iban) or ""
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"


class Pedido(models.Model):
    """Un pedido hecho a un proveedor. Antes vivía en la hoja Pedidos_2026 del Excel.

    `revisar` sustituye a la hoja `pendiente_revisar`: Alberto quiere mirar sus facturas.
    """

    numero = models.CharField(max_length=20, unique=True)  # PO-2026-0001
    proveedor = models.ForeignKey(Proveedor, on_delete=models.CASCADE, related_name="pedidos")
    importe = models.DecimalField(max_digits=12, decimal_places=2)
    fecha = models.DateField(null=True, blank=True)
    revisar = models.BooleanField(default=False)
    nota = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["numero"]

    def __str__(self) -> str:
        return f"{self.numero} · {self.proveedor.codigo}"


# --- Asistente (chatbot de «Preguntar») -------------------------------------------------------


class Pregunta(models.Model):
    """Cada pregunta de Alberto al asistente: cuánto tardó y cuánto costó (para #31)."""

    cuando = models.DateTimeField(auto_now_add=True)
    texto = models.TextField()
    respuesta = models.TextField(blank=True)
    ok = models.BooleanField(default=True)
    error = models.TextField(blank=True)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    segundos = models.FloatField(default=0)

    class Meta:
        ordering = ["-cuando"]

    def __str__(self) -> str:
        return f"{self.cuando:%d/%m %H:%M} · {self.texto[:60]}"
