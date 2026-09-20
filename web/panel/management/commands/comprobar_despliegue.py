"""Dice en llano qué le falta al entorno para que la web viva fuera del portátil. Ver docs/despliegue.md.

Cada comprobación es una línea: «Bien», «Falta» o «Aviso». Si falta algo, termina con error (código 1),
así sirve igual en un terminal que en el arranque del contenedor.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import NamedTuple

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

CLAVE_DE_DESARROLLO = "solo-desarrollo-no-usar-en-produccion"
LOCALES = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


class Comprobacion(NamedTuple):
    nivel: str  # Bien, Falta o Aviso
    texto: str


def bien(texto: str) -> Comprobacion:
    return Comprobacion("Bien", texto)


def falta(texto: str) -> Comprobacion:
    return Comprobacion("Falta", texto)


def aviso(texto: str) -> Comprobacion:
    return Comprobacion("Aviso", texto)


def comprobaciones() -> list[Comprobacion]:
    return [*_django(), *_claves(), *_erp_y_fecha(), *_base_de_datos(), _almacen(), _estaticos()]


def _django() -> list[Comprobacion]:
    hosts = [h for h in settings.ALLOWED_HOSTS if h not in LOCALES]
    origenes = [o for o in settings.CSRF_TRUSTED_ORIGINS if o.startswith("https://")]
    resultado = [
        bien("DJANGO_DEBUG está apagado") if not settings.DEBUG
        else falta("DJANGO_DEBUG=0: con el modo de desarrollo encendido la web enseña errores con detalle a cualquiera"),
        bien("DJANGO_SECRET_KEY es propia y larga") if settings.SECRET_KEY != CLAVE_DE_DESARROLLO and len(settings.SECRET_KEY) >= 50
        else falta("DJANGO_SECRET_KEY: una clave propia de 50 caracteres o más (python -c \"import secrets; print(secrets.token_urlsafe(50))\")"),
        bien(f"DJANGO_ALLOWED_HOSTS admite {', '.join(hosts)}") if hosts
        else falta("DJANGO_ALLOWED_HOSTS: el dominio por el que se abrirá la web (facturas.tudominio.com)"),
        bien(f"CSRF_TRUSTED_ORIGINS confía en {', '.join(origenes)}") if origenes
        else falta("CSRF_TRUSTED_ORIGINS: el mismo dominio con https:// delante; sin esto los formularios se rechazan"),
    ]
    # La clave de acceso es opcional (Cloudflare Access también pone puerta): sin ella se avisa, no se impide.
    if settings.WEB_CLAVE:
        resultado.append(bien("WEB_CLAVE está: la web pide la clave antes de entrar"))
    elif not settings.DEBUG:
        resultado.append(aviso("WEB_CLAVE=… : sin clave, cualquiera con la dirección entra"))
    return resultado


def _claves() -> list[Comprobacion]:
    helmcode = os.getenv("HELMCODE_API_KEY", "")
    asistente = os.getenv("ASISTENTE_API_KEY", "") or helmcode
    return [
        bien("HELMCODE_API_KEY está") if helmcode
        else falta("HELMCODE_API_KEY: sin ella no se leen los escaneos ni se evalúan las notas"),
        bien("El asistente de «Preguntar» tiene clave") if asistente
        else falta("ASISTENTE_API_KEY (o HELMCODE_API_KEY): sin ella «Preguntar» no contesta"),
    ]


def _erp_y_fecha() -> list[Comprobacion]:
    erp = os.getenv("ERP_URL", "")
    host = erp.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    resultado = [
        bien(f"ERP_URL apunta a {erp}") if erp and host not in LOCALES
        else falta("ERP_URL: desde fuera del portátil 127.0.0.1 no es el ERP de Alberto; hay que decir dónde está (túnel o servicio aparte)"),
    ]
    resultado.append(
        bien(f"HOY fija la fecha de referencia en {os.environ['HOY']}") if os.getenv("HOY")
        else aviso("HOY no está: «fecha no futura» se mira contra el día de hoy y los resultados cambian con el calendario")
    )
    return resultado


def _base_de_datos() -> list[Comprobacion]:
    resultado = [
        bien("La base de datos es Postgres") if connection.vendor == "postgresql"
        else falta("DATABASE_URL=postgresql://…: SQLite vale para uno en su portátil, no para un servidor con varios hilos y un disco que puede cambiar"),
    ]
    try:
        connection.ensure_connection()
    except Exception as e:  # noqa: BLE001 — cualquier fallo de conexión se cuenta igual, en llano
        resultado.append(falta(f"No consigo conectar a la base de datos: {e}"))
        return resultado
    resultado.append(bien("Conecto con la base de datos"))
    ejecutor = MigrationExecutor(connection)
    pendientes = ejecutor.migration_plan(ejecutor.loader.graph.leaf_nodes())
    resultado.append(
        bien("Las tablas están al día") if not pendientes
        else falta(f"Faltan {len(pendientes)} migraciones por aplicar: python manage.py migrate")
    )
    return resultado


def _almacen() -> Comprobacion:
    almacen = Path(settings.MEDIA_ROOT)
    try:
        almacen.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=almacen, prefix=".prueba-", delete=True):
            pass
    except OSError as e:
        return falta(f"No puedo escribir en el almacén ({almacen}): {e}. ALMACEN_DIR tiene que ser un disco persistente con permisos")
    return bien(f"El almacén se puede escribir ({almacen})")


def _estaticos() -> Comprobacion:
    hoja = Path(settings.STATIC_ROOT) / "panel" / "panel.css"
    if hoja.is_file():
        return bien(f"Los estáticos están recogidos en {settings.STATIC_ROOT}")
    return falta(f"Los estáticos no están recogidos en {settings.STATIC_ROOT}: python manage.py collectstatic --noinput")


class Command(BaseCommand):
    help = "Comprueba qué le falta al entorno para servir la web fuera del portátil (variables, base de datos, almacén, estáticos)."

    def handle(self, *args, **opciones) -> None:
        resultado = comprobaciones()
        for nivel, texto in resultado:
            self.stdout.write(f"{nivel:<6} {texto}")
        faltan = sum(1 for c in resultado if c.nivel == "Falta")
        if faltan:
            raise CommandError(f"Faltan {faltan} cosas para desplegar." if faltan > 1 else "Falta 1 cosa para desplegar.")
        self.stdout.write("Todo listo para desplegar.")
