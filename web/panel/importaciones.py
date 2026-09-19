"""«Importar datos»: los ficheros de proveedores y de pedidos que Alberto sube por la web, con vista previa.

Cada fichero se lee con el adaptador de los CSV de altas (`csv_altas.py`, el mismo que usa el comando
`importar_maestro`) y se reconoce por sus cabeceras. Después cada fila se clasifica contra lo que ya
hay en el maestro: nuevo, ya está igual, cambia (qué campo, antes y después) o inválido (y por qué).
Cuando Alberto pulsa «Aplicar», lo válido entra por `MaestroDjango.importar`, que no pisa lo que él
haya marcado o anotado. Entre subir y aplicar, lo parseado espera en `MEDIA_ROOT/importaciones/
<token>.json` (no en la sesión); los de más de un día se borran. La clasificación se vuelve a hacer
al aplicar, con el maestro de ese momento, por si algo cambió entre los dos pasos.
"""
from __future__ import annotations

import csv
import json
import re
import secrets
import time
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db.models import QuerySet

from upistas.adaptadores.fuentes.csv_altas import ILEGIBLE, tabla_csv, tipo_de_fichero
from upistas.adaptadores.fuentes.filas import (
    PATRON_PEDIDO,
    importe_de_fila,
    nif_valido,
    pedido_de_fila,
    proveedor_de_fila,
    texto,
    valor_importe,
)
from upistas.adaptadores.fuentes.memoria import MaestroEnMemoria
from upistas.adaptadores.persistencia.django_maestro import CENTIMOS, MaestroDjango, plural
from upistas.dominio.modelos import Pedido, Proveedor
from web.panel.models import Importacion
from web.panel.models import Pedido as FilaPedido
from web.panel.models import Proveedor as FilaProveedor

NUEVO, IGUAL, CAMBIA, INVALIDO = "nuevo", "igual", "cambia", "invalido"
ETIQUETAS = {NUEVO: "Nuevo", IGUAL: "Ya está igual", CAMBIA: "Cambia", INVALIDO: "No vale"}
PILDORAS = {NUEVO: "bien", IGUAL: "neutra", CAMBIA: "ojo", INVALIDO: "mal"}
TIPOS = {"proveedores": "Fichero de proveedores", "pedidos": "Fichero de pedidos"}
ESTADOS_PEDIDO = {"ABIERTO", "PENDIENTE", "PAGADA", "CERRADO"}
PATRON_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
PATRON_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,32}$")
CARPETA = "importaciones"
UN_DIA = 24 * 3600

# Lo más largo que cabe en cada columna de la tabla de proveedores (SQLite no lo impide; nosotros sí).
# El número de pedido no hace falta: PATRON_PEDIDO ya lo deja en 12 letras, y la columna admite 20.
TOPES_PROVEEDOR = tuple(
    (campo, FilaProveedor._meta.get_field(columna).max_length, etiqueta)
    for columna, campo, etiqueta in (("codigo", "id", "El código"), ("nombre", "nombre", "El nombre"), ("nif", "nif", "El NIF"),
                                     ("iban", "iban", "La cuenta"), ("ciudad", "ciudad", "La ciudad"))
)

# Columna del fichero → campo del proveedor → cómo se le llama a Alberto.
CAMPOS_PROVEEDOR = (
    ("razonsocial", "nombre", "Nombre"),
    ("nif", "nif", "NIF"),
    ("iban", "iban", "Cuenta"),
    ("ciudad", "ciudad", "Ciudad"),
    ("condiciones", "condiciones_dias", "Días de pago"),
)


@dataclass
class Fichero:
    """Un fichero subido, ya parseado. Es lo que se guarda entre el paso de subir y el de aplicar."""

    nombre: str
    tipo: str | None  # proveedores | pedidos | None si no se reconoce
    columnas: list[str] = field(default_factory=list)  # cabeceras normalizadas
    filas: list[dict] = field(default_factory=list)
    aviso: str = ""  # por qué no vale, o qué reparo tiene aunque se lea, en palabras de Alberto

    @property
    def titulo(self) -> str:
        return TIPOS.get(self.tipo, "Fichero")


@dataclass
class Fila:
    numero: int  # la línea del fichero (la cabecera es la 1)
    estado: str
    clave: str  # el código del proveedor o el número del pedido
    texto: str  # lo que trae, en una línea
    motivo: str = ""  # si no vale, por qué
    aviso: str = ""  # vale y entra, pero trae algo que Alberto debería saber
    cambios: list[dict] = field(default_factory=list)  # [{"campo", "antes", "despues"}]

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS[self.estado]

    @property
    def pildora(self) -> str:
        return "ojo" if self.aviso else PILDORAS[self.estado]


@dataclass
class VistaFichero:
    fichero: Fichero
    filas: list[Fila]

    def cuantas(self, estado: str) -> int:
        return sum(1 for f in self.filas if f.estado == estado)

    @property
    def resumen(self) -> str:
        partes = [(NUEVO, "nueva", "nuevas"), (CAMBIA, "cambia", "cambian"), (IGUAL, "ya estaba", "ya estaban"),
                  (INVALIDO, "no vale", "no valen")]
        return ", ".join(plural(self.cuantas(e), uno, varios) for e, uno, varios in partes if self.cuantas(e))


@dataclass
class Previsualizacion:
    ficheros: list[VistaFichero]
    proveedores: list[Proveedor]  # lo válido que se aplicará (nuevos y cambios)
    pedidos: list[Pedido]
    avisos: list[str]

    def cuantas(self, estado: str, tipo: str | None = None) -> int:
        return sum(v.cuantas(estado) for v in self.ficheros if tipo is None or v.fichero.tipo == tipo)

    @property
    def hay_algo_que_aplicar(self) -> bool:
        return bool(self.proveedores or self.pedidos)

    @property
    def recuento(self) -> str:
        """«4 proveedores nuevos, 39 pedidos nuevos, 1 cambia, 2 filas inválidas»."""
        partes = []
        if any(v.fichero.tipo == "proveedores" for v in self.ficheros):
            partes.append(plural(self.cuantas(NUEVO, "proveedores"), "proveedor nuevo", "proveedores nuevos"))
        if any(v.fichero.tipo == "pedidos" for v in self.ficheros):
            partes.append(plural(self.cuantas(NUEVO, "pedidos"), "pedido nuevo", "pedidos nuevos"))
        partes.append(plural(self.cuantas(CAMBIA), "cambia", "cambian"))
        partes.append(plural(self.cuantas(INVALIDO), "fila inválida", "filas inválidas"))
        return ", ".join(partes)


# --- paso 1: leer lo que sube ---------------------------------------------------------------------


def leer(nombre: str, datos: bytes) -> Fichero:
    """Parsea un fichero subido y dice si es de proveedores, de pedidos o ninguna de las dos cosas."""
    avisos: list[str] = []
    try:
        columnas, filas = tabla_csv(nombre, datos, avisos)
    except (csv.Error, UnicodeDecodeError):
        return Fichero(nombre, None, aviso=f"«{nombre}» no se puede leer como un fichero de texto con columnas.")
    if not columnas:
        return Fichero(nombre, None, aviso=f"«{nombre}» está vacío.")
    tipo = tipo_de_fichero(columnas)
    if tipo is None:
        return Fichero(nombre, None, columnas, aviso=(
            f"«{nombre}» no es un fichero de proveedores ni de pedidos: no tiene sus columnas "
            "(ID, Razon Social, NIF, IBAN… o pedido, proveedor_id, importe_total…)."))
    if not filas:
        return Fichero(nombre, None, columnas, aviso=f"«{nombre}» solo trae la cabecera, ninguna fila.")
    aviso = ""
    if any(ILEGIBLE in a for a in avisos):  # se lee igual, pero que Alberto sepa que algo sale mal escrito
        aviso = f"«{nombre}» {ILEGIBLE}: donde debía haber una letra sale «�». Revise los nombres antes de aplicar."
    return Fichero(nombre, tipo, columnas, filas, aviso)


def guardar(ficheros: list[Fichero]) -> str:
    """Deja lo parseado esperando a que Alberto lo vea y decida. Devuelve el token de la vista previa."""
    carpeta = _carpeta()
    carpeta.mkdir(parents=True, exist_ok=True)
    _borrar_viejos(carpeta)
    token = secrets.token_urlsafe(12)
    (carpeta / f"{token}.json").write_text(json.dumps([f.__dict__ for f in ficheros], ensure_ascii=False), encoding="utf-8")
    return token


def cargar(token: str) -> list[Fichero] | None:
    ruta = _ruta(token)
    if ruta is None or not ruta.is_file():
        return None
    return [Fichero(**f) for f in json.loads(ruta.read_text(encoding="utf-8"))]


def borrar(token: str) -> None:
    ruta = _ruta(token)
    if ruta is not None and ruta.is_file():
        ruta.unlink()


def _carpeta() -> Path:
    return Path(settings.MEDIA_ROOT) / CARPETA


def _ruta(token: str) -> Path | None:
    return _carpeta() / f"{token}.json" if PATRON_TOKEN.match(token or "") else None


def _borrar_viejos(carpeta: Path) -> None:
    limite = time.time() - UN_DIA
    for ruta in carpeta.glob("*.json"):
        if ruta.stat().st_mtime < limite:
            ruta.unlink(missing_ok=True)


# --- paso 2: la vista previa, fila a fila contra el maestro -----------------------------------------


def previsualizar(ficheros: list[Fichero]) -> Previsualizacion:
    """Clasifica cada fila. Primero los ficheros de proveedores, para que los pedidos del mismo envío
    puedan apuntar a un proveedor que llega con ellos."""
    existentes = {p.codigo: p for p in FilaProveedor.objects.all()}
    por_nif = {p.nif: p for p in existentes.values()}
    conocidos: dict[str, Proveedor] = {  # código → cómo se llama y qué NIF tiene, para los pedidos
        p.codigo: Proveedor(p.codigo, p.nombre, p.nif, p.iban, p.ciudad, p.condiciones_dias) for p in existentes.values()
    }
    envio: dict[str, tuple[str, int]] = {}  # código o número → (fichero, fila) donde ya venía
    envio_nif: dict[str, str] = {}
    vistas: list[VistaFichero] = []
    proveedores: list[Proveedor] = []
    pedidos: list[Pedido] = []
    avisos = [f.aviso for f in ficheros if f.aviso]  # los que no valen y los que se leen con reparos

    for fichero in sorted(ficheros, key=lambda f: f.tipo != "proveedores"):
        if fichero.tipo == "proveedores":
            filas = _proveedores(fichero, existentes, por_nif, conocidos, envio, envio_nif, proveedores)
        elif fichero.tipo == "pedidos":
            filas = _pedidos(fichero, conocidos, envio, pedidos)
        else:
            continue
        vistas.append(VistaFichero(fichero, filas))
    return Previsualizacion(vistas, proveedores, pedidos, avisos)


def _proveedores(fichero: Fichero, existentes: dict, por_nif: dict, conocidos: dict[str, Proveedor],
                 envio: dict, envio_nif: dict, a_aplicar: list[Proveedor]) -> list[Fila]:
    filas: list[Fila] = []
    for numero, datos in enumerate(fichero.filas, start=2):
        p = proveedor_de_fila(datos)
        fila = Fila(numero, INVALIDO, p.id, f"{p.nombre} · {p.nif}".strip(" ·"))
        filas.append(fila)
        fila.motivo = _fallo_proveedor(p, existentes, por_nif, envio, envio_nif)
        if fila.motivo:
            continue
        existente = existentes.get(p.id)
        if existente is None:
            fila.estado = NUEVO
        else:
            for columna, campo, etiqueta in CAMPOS_PROVEEDOR:
                if columna not in fichero.columnas:  # lo que el fichero no trae se deja como está
                    p = replace(p, **{campo: getattr(existente, campo)})
                elif getattr(existente, campo) != getattr(p, campo):
                    fila.cambios.append({"campo": etiqueta, "antes": _bonito(getattr(existente, campo)), "despues": _bonito(getattr(p, campo))})
            fila.estado = CAMBIA if fila.cambios else IGUAL
        envio[p.id] = (fichero.nombre, numero)
        envio_nif[p.nif] = p.id
        conocidos[p.id] = p
        if fila.estado != IGUAL:
            a_aplicar.append(p)
    return filas


def _fallo_proveedor(p: Proveedor, existentes: dict, por_nif: dict, envio: dict, envio_nif: dict) -> str:
    if not p.id:
        return "No trae código de proveedor."
    if not p.nombre:
        return "No trae el nombre."
    if not p.nif:
        return "No trae el NIF."
    for campo, tope, etiqueta in TOPES_PROVEEDOR:
        if len(getattr(p, campo)) > tope:
            return f"{etiqueta} «{getattr(p, campo)}» es demasiado largo: como mucho {tope} caracteres."
    if not nif_valido(p.nif):
        return f"El NIF «{p.nif}» no tiene un formato conocido."
    if not p.iban:
        return "No trae la cuenta."
    if not PATRON_IBAN.match(p.iban) or (p.iban.startswith("ES") and len(p.iban) != 24):
        return f"La cuenta «{p.iban}» no es un IBAN."
    if p.id in envio:
        return f"Repetido: ya venía en la fila {envio[p.id][1]}."
    otro = por_nif.get(p.nif)
    if otro is not None and otro.codigo != p.id:
        return f"El NIF {p.nif} ya es de {otro.nombre} ({otro.codigo})."
    if envio_nif.get(p.nif, p.id) != p.id:
        return f"El NIF {p.nif} ya lo lleva {envio_nif[p.nif]} en este mismo envío."
    return ""


def _pedidos(fichero: Fichero, conocidos: dict[str, Proveedor], envio: dict, a_aplicar: list[Pedido]) -> list[Fila]:
    existentes = {f.numero: f for f in FilaPedido.objects.select_related("proveedor")}
    filas: list[Fila] = []
    for numero, datos in enumerate(fichero.filas, start=2):
        pid = texto(datos.get("pedido")).upper()
        importe = importe_de_fila(datos)
        proveedor = conocidos.get(texto(datos.get("proveedorid")).upper())
        fila = Fila(numero, INVALIDO, pid, _que_trae(datos, proveedor, importe))
        filas.append(fila)
        fila.motivo = _fallo_numero_e_importe(pid, importe, datos, envio)
        if fila.motivo:
            continue
        p = pedido_de_fila(datos, importe, "ABIERTO")
        fila.texto = _que_trae(datos, proveedor, importe, p.fecha)
        fila.motivo = _fallo_pedido(p, datos, proveedor)
        if fila.motivo:
            continue
        fila.aviso = _reparo_pedido(p, proveedor)
        existente = existentes.get(pid)
        if existente is None:
            fila.estado = NUEVO
        else:
            if "fechapedido" not in fichero.columnas:
                p = replace(p, fecha=existente.fecha)
            comparables = (("Proveedor", existente.proveedor.codigo, p.proveedor_id),
                           ("Importe", existente.importe, p.importe.quantize(CENTIMOS)),
                           ("Fecha", existente.fecha, p.fecha))
            fila.cambios = [{"campo": c, "antes": _bonito(a), "despues": _bonito(d)} for c, a, d in comparables if a != d]
            fila.estado = CAMBIA if fila.cambios else IGUAL
        envio[pid] = (fichero.nombre, numero)
        if fila.estado != IGUAL:
            a_aplicar.append(p)
    return filas


def _que_trae(datos: dict, proveedor: Proveedor | None, importe: Decimal | None, fecha=None) -> str:
    """«Ofimática Cieza S.L. · 3.139,66 € · 17/08/2026»; lo que no se entiende, tal cual venía."""
    crudo = texto(valor_importe(datos))
    quien = proveedor.nombre if proveedor else texto(datos.get("proveedorid")).upper()
    cuanto = _bonito(importe) if importe is not None else crudo
    cuando = _bonito(fecha) if fecha is not None else texto(datos.get("fechapedido"))
    return " · ".join(t for t in (quien, cuanto, cuando) if t)


def _fallo_numero_e_importe(pid: str, importe: Decimal | None, datos: dict, envio: dict) -> str:
    if not pid:
        return "No trae número de pedido."
    if not PATRON_PEDIDO.match(pid):
        return f"El número «{pid}» no tiene la forma PO-2026-0001."
    if pid in envio:
        return f"Repetido: ya venía en la fila {envio[pid][1]}."
    if importe is None:
        crudo = texto(valor_importe(datos))
        return f"El importe «{crudo}» no es un número." if crudo else "No trae importe."
    if importe <= 0:
        return "El importe tiene que ser mayor que cero."
    return ""


def _fallo_pedido(p: Pedido, datos: dict, proveedor: Proveedor | None) -> str:
    fecha_cruda = texto(datos.get("fechapedido"))
    if fecha_cruda and p.fecha is None:
        return f"La fecha «{fecha_cruda}» no se entiende."
    if PATRON_PEDIDO.match(p.estado):
        return f"En la columna del estado viene otro pedido ({p.estado}): las columnas no cuadran."
    if not p.proveedor_id:
        return "No trae el código del proveedor."
    if proveedor is None:
        return f"El proveedor {p.proveedor_id} no está dado de alta ni viene en este envío."
    return ""


def _reparo_pedido(p: Pedido, proveedor: Proveedor) -> str:
    """Lo que no impide importar (el pedido no guarda ni estado ni NIF) pero conviene que Alberto vea."""
    if p.estado not in ESTADOS_PEDIDO:
        return f"El estado «{p.estado}» no se conoce; el pedido entra igual, el estado no se guarda."
    if p.nif and p.nif != proveedor.nif:
        return f"El NIF {p.nif} no es el de {proveedor.nombre} ({proveedor.id}); el pedido entra con {proveedor.id}."
    return ""


def _bonito(valor) -> str:
    """Cómo se enseña un valor en la tabla: importes a la española, fechas día/mes/año, vacío si no hay."""
    if valor is None or valor == "":
        return "—"
    if isinstance(valor, Decimal):
        entero, decimales = f"{valor:,.2f}".split(".")
        return f"{entero.replace(',', '.')},{decimales} €"
    if hasattr(valor, "strftime"):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


# --- paso 3: aplicar solo lo válido ------------------------------------------------------------------


def aplicar(ficheros: list[Fichero]) -> Importacion:
    """Vuelca en el maestro lo que la vista previa da por válido y lo apunta en «Últimas importaciones»."""
    vista = previsualizar(ficheros)
    resumen = MaestroDjango().importar(MaestroEnMemoria(vista.proveedores, vista.pedidos))
    return Importacion.objects.create(
        ficheros=", ".join(f.nombre for f in ficheros)[:255],
        nuevos=resumen.proveedores_nuevos + resumen.pedidos_nuevos,
        cambiados=resumen.cambiados,
        invalidos=vista.cuantas(INVALIDO),
    )


def ultimas(cuantas: int = 8) -> QuerySet[Importacion]:
    return Importacion.objects.all()[:cuantas]
