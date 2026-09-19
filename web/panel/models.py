"""Nuestra base de datos. El ERP de Alberto nunca se toca: aquí guardamos una copia versionada."""
from django.db import models


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
