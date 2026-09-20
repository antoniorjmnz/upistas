"""Marcar en un PDF lo que hace saltar las alarmas y el texto que no se ve, para que Alberto lo vea con sus ojos.

El original no se toca: se devuelve una copia. Cada trozo escondido va rodeado en rojo en su página;
cada dato que hace fallar una comprobación (la cuenta que no es la del maestro, el total que no cuadra
con el pedido, la fecha imposible, la nota que mete prisa) va rodeado en naranja con una etiqueta corta
al lado. Al final, una página nueva empieza por el resultado y su motivo, lista las alarmas y dónde
están, transcribe lo escondido y dice qué no se ha podido leer. Aquí se decide qué se busca, qué se
escribe y en qué orden; cómo se abre el PDF, cómo se busca y cómo se dibuja lo sabe el adaptador.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

TITULO = "Texto escondido que hemos encontrado"
SIN_COMPROBAR = "No hemos podido comprobar si lleva texto escondido"  # la misma frase que ve Alberto en el detalle
INTRO = (
    "Estos trozos estaban en la factura, pero no se veían al abrirla. Los hemos rodeado en rojo en su página. "
    "No se tienen en cuenta para decidir: se decide con los datos."
)
ALARMAS = "Lo que ha hecho saltar la alarma"
INTRO_ALARMAS = (
    "Cada dato que no cuadra va rodeado en naranja en su página, con una nota corta al lado que dice qué le pasa. "
    "Esta copia es solo para mirar: la factura original no se toca."
)
SIN_ALARMAS = "Esta factura no ha hecho saltar ninguna alarma: cumple todas las comprobaciones."
INCOMPLETO = "Lo que no hemos podido leer"
MAX_CARACTERES = 2000  # por trozo: más que esto ya no es una frase escondida; se recorta y se avisa con «…»
MAX_COINCIDENCIAS = 6  # un mismo dato repetido por toda la factura no se rodea más veces que esto
MAX_NOTA = 80  # caracteres de una nota que se buscan si no aparece entera ni su primera frase
ENCABEZADOS = frozenset({ALARMAS, TITULO, INCOMPLETO, SIN_COMPROBAR})  # el adaptador los escribe como títulos
# La coletilla que el pie de la plantilla pega al final de la última nota: no forma parte de ella y, si se
# buscara con ella, el recuadro bajaría hasta el pie de la hoja.
PIE_DE_PLANTILLA = re.compile(r"\s*documento generado por\b[^.]*\.?\s*$", re.IGNORECASE)

# Por qué no se veía, dicho como se lo diríamos a Alberto. La clave es el motivo que apunta el inspector.
MOTIVOS = {
    "modo de texto invisible": "escrito en modo invisible",
    "texto transparente": "escrito transparente",
    "texto de tamaño ínfimo": "con letra minúscula",
    "texto fuera del área visible": "fuera de la hoja",
    "texto casi blanco sin fondo oscuro comprobable": "escrito en blanco sobre blanco",
    "texto potencialmente tapado por contenido posterior": "tapado por algo dibujado encima",
}


@dataclass(frozen=True)
class TrozoOculto:
    """Un trozo de texto que no se ve al abrir el PDF: dónde está, qué dice y por qué se esconde."""

    pagina: int  # empezando en 1
    caja: tuple[float, float, float, float]  # x0, y0, x1, y1 en puntos, dentro de su página
    texto: str
    motivos: tuple[str, ...]


@dataclass(frozen=True)
class OcultosDelPdf:
    trozos: tuple[TrozoOculto, ...]
    sin_comprobar: tuple[int, ...] = ()  # páginas que no se pudieron revisar: demasiado complejas o ilegibles


@dataclass(frozen=True)
class Hallazgo:
    """Dónde aparece un texto en el PDF."""

    pagina: int  # empezando en 1
    caja: tuple[float, float, float, float]


@dataclass(frozen=True)
class Marca:
    """Un recuadro naranja con su etiqueta: «IBAN distinto del maestro» junto a la cuenta. Si dos reglas
    señalan el mismo dato, la etiqueta lleva las dos, una por línea."""

    pagina: int
    caja: tuple[float, float, float, float]
    etiqueta: str


@dataclass(frozen=True)
class CampoLeido:
    """Un dato tal como lo leyó el lector: el valor ya limpio y el texto literal del que salió."""

    valor: object = None
    fuente: str | None = None


@dataclass(frozen=True)
class ReglaFallida:
    id: str
    detalle: str = ""
    texto: str = ""  # en palabras de Alberto («El IVA o el total no cuadran»); si falta, se usa el id


@dataclass(frozen=True)
class Alarmas:
    """Lo que hizo saltar las alarmas en una factura, tal como lo guardó la decisión."""

    resultado: str  # en palabras de Alberto: Pagar, No pagar, Revisar
    motivo: str  # el motivo corto
    reglas: tuple[ReglaFallida, ...] = ()  # solo las que fallan
    campos: Mapping[str, CampoLeido] = field(default_factory=dict)
    notas: tuple[str, ...] = ()  # el texto de la factura que no decide
    sin_leer: tuple[str, ...] = ()  # lo que no aparece o no se pudo leer, ya en palabras de Alberto («la fecha»)
    errores: tuple[str, ...] = ()  # lo que dijo el lector al fallar
    alertas: tuple[str, ...] = ()  # avisos del fichero, aunque la decisión sea clara


class PdfNoMarcable(Exception):
    """El PDF no se puede abrir o recorrer: cifrado, dañado o demasiado grande. El mensaje es para Alberto."""


class MarcadorPdf(Protocol):
    """Lo que hace falta del mundo exterior: encontrar lo escondido, localizar textos y dibujar encima."""

    def ocultos(self, ruta: Path) -> OcultosDelPdf: ...

    def localizar(self, ruta: Path, textos: Sequence[str]) -> Mapping[str, tuple[Hallazgo, ...]]:
        """Dónde aparece cada texto (tal cual, también partido en dos líneas). Los que no están, no vienen."""
        ...

    def marcar(self, ruta: Path, trozos: Sequence[TrozoOculto], marcas: Sequence[Marca], pagina_final: Sequence[str]) -> bytes:
        """Una copia del PDF con cada trozo rodeado en rojo, cada marca rodeada en naranja con su etiqueta y,
        si hay párrafos, una página nueva al final con ellos (el primero es el título; los que estén en
        ENCABEZADOS van como títulos de apartado). Sin párrafos no se añade ninguna página."""
        ...


@dataclass(frozen=True)
class PdfMarcado:
    datos: bytes
    frases: tuple[str, ...]  # lo que dice la página final, en orden; vacío si el PDF salió limpio
    marcas: tuple[Marca, ...] = ()  # las naranjas


@dataclass(frozen=True)
class Busqueda:
    """Un dato que hay que rodear por una regla: qué textos probar (por orden) y qué poner al lado."""

    regla: str
    etiqueta: str
    textos: tuple[str, ...]


def marcar_pdf(ruta: Path, marcador: MarcadorPdf, alarmas: Alarmas | None = None) -> PdfMarcado:
    """La copia marcada de un PDF y lo que se le ha escrito al final. Lanza PdfNoMarcable si no se puede.

    Sin `alarmas` solo se señala lo escondido (y sin nada escondido no hay página final). Con ellas se
    rodea además cada dato que falla y la página final siempre existe: aunque sea para decir que está limpio.
    """
    encontrado = marcador.ocultos(ruta)
    if alarmas is None:
        frases = pagina_final(encontrado)
        return PdfMarcado(marcador.marcar(ruta, encontrado.trozos, (), frases), frases)
    busquedas = busquedas_de(alarmas)
    textos = list(dict.fromkeys(t for b in busquedas for t in b.textos))
    hallado = marcador.localizar(ruta, textos) if textos else {}
    marcas, donde = senalar(busquedas, hallado)
    frases = pagina_final_con_alarmas(alarmas, donde, encontrado)
    return PdfMarcado(marcador.marcar(ruta, encontrado.trozos, marcas, frases), frases, tuple(marcas))


# --- Qué se busca por cada regla que falla ---------------------------------------------------------


def busquedas_de(alarmas: Alarmas) -> list[Busqueda]:
    """Para cada comprobación fallida, los datos que hay que rodear y qué decir al lado."""
    busquedas: list[Busqueda] = []
    for regla in alarmas.reglas:
        for textos, etiqueta in _que_senalar(regla, alarmas):
            busquedas.append(Busqueda(regla.id, etiqueta, textos))
    return busquedas


def _que_senalar(r: ReglaFallida, a: Alarmas) -> list[tuple[tuple[str, ...], str]]:
    """(textos que probar, etiqueta) por cada dato implicado en esa regla. Nada si no hay nada que rodear."""
    d = r.detalle or ""
    campo = lambda nombre: textos_de_campo(a.campos.get(nombre))  # noqa: E731
    notas = [(textos_de_nota(n), "Texto que intenta influir en la decisión") for n in a.notas]
    if r.id == "R1_nif_iban":
        if "IBAN" in d:
            return [(campo("iban"), "Cuenta distinta de la del maestro")]
        return [(campo("nif"), "NIF que no está en el maestro")]
    if r.id == "R2_pedido_importe":
        importe = re.search(r"del pedido (-?[\d.,]+)", d)
        if importe:
            return [(campo("total"), f"Total distinto del pedido: {_euros(importe.group(1))}"), (campo("pedido"), "Pedido con el que no cuadra el total")]
        if "no pertenece" in d:
            return [(campo("pedido"), "Pedido de otro proveedor"), (campo("nif"), "NIF que no es el del pedido")]
        return [(campo("pedido"), "Pedido que no está en el ERP")]
    if r.id == "R3_iva_total":
        if "cuota" in d:
            return [(campo("base"), "Base"), (campo("iva"), "IVA que no corresponde a la base"), (campo("total"), "Total")]
        return [(campo("base"), "Base"), (campo("iva"), "IVA"), (campo("total"), "Total que no es base más IVA")]
    if r.id == "R2_divisa":  # «Factura en USD (2.450,00 USD); el pedido es de 2.254,00 €: …»
        moneda = re.search(r"Factura en ([A-Z]{3})", d)
        etiqueta = f"Importe en {moneda.group(1)}: el pedido va en euros" if moneda else "Importe en otra moneda"
        return [(campo("total"), etiqueta), (campo("pedido"), "Pedido en euros con el que se compara")]
    if r.id == "R3_datos_fiscales":
        if "cobra IVA español" in d:
            return [(campo("iva_pct") or campo("iva"), "IVA español de un proveedor de fuera"), (campo("nif"), "NIF de fuera de España")]
        etiqueta = "Importe negativo" if "negativ" in d else "Importe que no se puede comprobar"
        return [(campo(n), etiqueta) for n in ("base", "iva", "total")]
    if r.id == "R4_fecha":
        etiqueta = "Fecha futura" if "futura" in d else "Fecha que no se lee bien" if "ilegible" in d else "Fecha imposible"
        return [(campo("fecha"), etiqueta)]
    if r.id in ("R5_erp_pendiente", "R5_no_pagada"):
        if "pagad" in d.lower():
            return [(campo("pedido"), "Pedido ya pagado en el ERP")]
        if "aprobad" in d:
            return [(campo("pedido"), "Pedido ya aprobado en otra factura")]
        return [(campo("pedido"), "Pedido que el ERP no da como pendiente")]
    if r.id in ("R5_duplicado", "R5_hash_previo", "R5_copia_hash", "R5_reenvio"):
        return [(campo("numero_factura") or campo("pedido"), "Factura repetida")]
    if r.id in ("R6_notas", "R6_evaluacion_disponible"):
        return notas if r.id == "R6_notas" else [(t, "Nota que no se ha podido evaluar") for t, _ in notas]
    if r.id == "R6_revision_interna":  # la misma frase que ve en la cola: «Trae una nota que pide revisión»
        return [(campo("pedido"), "Pedido con una nota que pide revisión")]
    if r.id == "R7_marcado_por_alberto":
        return [(campo("pedido"), "Pedido que usted apuntó para revisar")]
    if r.id == "R6_proveedor_referencias" and "NIF de la factura" in d:
        return [(campo("nif"), "NIF que no es el del proveedor del pedido")]
    if r.id == "R8_importe_anomalo":
        return [(campo("total"), "Importe fuera de lo habitual")]
    if r.id == "R9_destinatario":
        return [(campo("cliente_cif"), "Va dirigida a otro cliente")]
    return []


def textos_de_campo(campo: CampoLeido | None) -> tuple[str, ...]:
    """Cómo puede aparecer un dato en la hoja, por orden de preferencia: el texto literal del que se leyó
    («TOTAL: 3.944,60»), y el valor escrito de las maneras habituales (3.944,60 · 3944.60 · ES02 2100 …)."""
    if campo is None:
        return ()
    textos: list[str] = []
    if campo.fuente and str(campo.fuente).strip():
        textos.append(" ".join(str(campo.fuente).split()))
    valor = campo.valor
    if isinstance(valor, bool) or valor in (None, ""):
        return tuple(dict.fromkeys(textos))
    if isinstance(valor, (int, float)):
        textos += _importes(float(valor))
    else:
        v = str(valor).strip()
        textos.append(v)
        if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", v):  # un IBAN: en la factura suele ir en grupos de cuatro
            textos.append(" ".join(v[i : i + 4] for i in range(0, len(v), 4)))
        fecha = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v)
        if fecha:
            a, m, dia = fecha.groups()
            textos += [f"{dia}/{m}/{a}", f"{int(dia)}/{int(m)}/{a}", f"{dia}-{m}-{a}", f"{dia}.{m}.{a}"]
    return tuple(dict.fromkeys(t for t in textos if t))


def _importes(valor: float) -> list[str]:
    """3944.6 → «3.944,60», «3944.60», «3944,60», «3,944.60» y, si es redondo, «3944»."""
    signo = "-" if valor < 0 else ""
    en = f"{abs(valor):,.2f}"  # 3,944.60
    llano = f"{abs(valor):.2f}"  # 3944.60
    es = en.replace(",", "|").replace(".", ",").replace("|", ".")  # 3.944,60
    formas = [es, llano, llano.replace(".", ","), en]
    if valor == int(valor):
        formas.append(str(abs(int(valor))))
    return [signo + f for f in formas]


def _euros(texto: str) -> str:
    """«12847.40» (como lo escribe la regla) → «12.847,40». Sin el símbolo del euro: la letra con la que
    el adaptador escribe las etiquetas lo pinta como un punto."""
    try:
        return _importes(float(texto.replace(",", ".")))[0]
    except ValueError:
        return texto


def textos_de_nota(nota: str) -> tuple[str, ...]:
    """La nota entera sin la coletilla del pie de plantilla y, por si va partida por algo que no es un
    salto de línea, su primera frase y sus primeros MAX_NOTA caracteres."""
    limpia = PIE_DE_PLANTILLA.sub("", " ".join(nota.split()))
    if not limpia:
        return ()
    primera = re.split(r"(?<=[.;:])\s", limpia, maxsplit=1)[0]
    principio = limpia if len(limpia) <= MAX_NOTA else limpia[:MAX_NOTA].rsplit(" ", 1)[0]  # sin partir una palabra
    return tuple(dict.fromkeys(t for t in (limpia, primera, principio.strip()) if len(t) >= 12))


# --- Dónde ha aparecido cada cosa -------------------------------------------------------------------


@dataclass(frozen=True)
class Sitio:
    """Qué se buscó por una regla y en qué páginas cayó (ninguna si no apareció)."""

    buscado: str  # el primer texto que se probó; vacío si el dato ni siquiera se leyó
    paginas: tuple[int, ...]
    etiqueta: str = ""  # lo que dice la marca


def senalar(busquedas: Sequence[Busqueda], hallado: Mapping[str, tuple[Hallazgo, ...]]) -> tuple[list[Marca], dict[str, list[Sitio]]]:
    """Las marcas naranjas y, por regla, dónde cayó cada dato buscado.

    De cada dato se rodea el primer texto que aparece, y como mucho MAX_COINCIDENCIAS veces. Dos reglas
    que señalan el mismo sitio no lo rodean dos veces: la etiqueta de la segunda se escribe debajo de la
    primera, en la misma marca (y si dicen lo mismo, una sola vez).
    """
    marcas: list[Marca] = []
    en_sitio: dict[tuple[int, tuple[float, float, float, float]], int] = {}  # qué marca hay en cada recuadro
    donde: dict[str, list[Sitio]] = {}
    for b in busquedas:
        hallazgos = next((hallado[t] for t in b.textos if hallado.get(t)), ())
        paginas = tuple(sorted({h.pagina for h in hallazgos}))
        donde.setdefault(b.regla, []).append(Sitio(b.textos[0] if b.textos else "", paginas, b.etiqueta))
        for h in hallazgos[:MAX_COINCIDENCIAS]:
            sitio = (h.pagina, h.caja)
            if sitio not in en_sitio:
                en_sitio[sitio] = len(marcas)
                marcas.append(Marca(h.pagina, h.caja, b.etiqueta))
                continue
            marca = marcas[en_sitio[sitio]]
            if b.etiqueta not in marca.etiqueta.split("\n"):
                marcas[en_sitio[sitio]] = Marca(marca.pagina, marca.caja, f"{marca.etiqueta}\n{b.etiqueta}")
    return marcas, donde


def _paginas(numeros: Sequence[int]) -> str:
    """«la página 1» o «las páginas 1, 2 y 3»."""
    if len(numeros) == 1:
        return f"la página {numeros[0]}"
    return "las páginas " + ", ".join(str(n) for n in numeros[:-1]) + f" y {numeros[-1]}"


# --- La página final --------------------------------------------------------------------------------


def pagina_final(encontrado: OcultosDelPdf) -> tuple[str, ...]:
    """Los párrafos de la página final: título, explicación, un párrafo por trozo y las páginas sin comprobar."""
    trozos = [frase(t) for t in encontrado.trozos]
    avisos = [f"{SIN_COMPROBAR} en la página {n}: mírela usted." for n in encontrado.sin_comprobar]
    if trozos:
        return (TITULO, INTRO, *trozos, *avisos)
    if avisos:
        return (SIN_COMPROBAR, *avisos)
    return ()


def pagina_final_con_alarmas(alarmas: Alarmas, donde: Mapping[str, Sequence[Sitio]], encontrado: OcultosDelPdf) -> tuple[str, ...]:
    """El resultado y su motivo, las alarmas (qué y dónde), lo escondido y lo que no se ha podido leer."""
    parrafos = [f"{alarmas.resultado}: {alarmas.motivo}"]
    # Dos reglas que se explican con la misma frase (R5_erp_pendiente y R5_no_pagada dicen las dos «El ERP
    # dice que ya está pagada») van en una sola línea, con los sitios de las dos.
    primera: dict[str, ReglaFallida] = {}
    sitios: dict[str, list[Sitio]] = {}
    for r in alarmas.reglas:
        que = r.texto or r.id
        primera.setdefault(que, r)
        sitios.setdefault(que, []).extend(donde.get(r.id, ()))
    lineas = [linea_de_alarma(primera[que], sitios[que], encontrado) for que in primera]
    lineas += [f"El fichero trae {a}." for a in alarmas.alertas if not a.startswith(("texto potencialmente oculto", "visibilidad del texto no verificable"))]
    if lineas:
        parrafos += [ALARMAS, INTRO_ALARMAS, *lineas]
    else:
        parrafos.append(SIN_ALARMAS)
    parrafos += pagina_final(encontrado)
    if alarmas.sin_leer or alarmas.errores:
        parrafos.append(INCOMPLETO)
        if alarmas.sin_leer:
            parrafos.append("No aparece o no se ha podido leer: " + ", ".join(alarmas.sin_leer) + ".")
        parrafos += [f"El lector avisó: {e}" for e in alarmas.errores]
    return tuple(parrafos)


def linea_de_alarma(r: ReglaFallida, sitios: Sequence[Sitio], encontrado: OcultosDelPdf) -> str:
    """«El pedido o el importe no cuadran con el ERP: señalado en naranja en la página 1.»"""
    que = r.texto or r.id
    if r.id == "R6_contenido_oculto":
        paginas = sorted({t.pagina for t in encontrado.trozos})
        return f"{que}: rodeado en rojo en {_paginas(paginas)}." if paginas else f"{que}: no se ve a simple vista, no hay nada que rodear."
    if not sitios:
        return f"{que}: no hay ningún dato que rodear en la factura."
    paginas = sorted({n for s in sitios for n in s.paginas})
    if paginas:
        etiquetas = list(dict.fromkeys(s.etiqueta for s in sitios if s.paginas and s.etiqueta))
        return f"{que}: señalado en naranja en {_paginas(paginas)} ({'; '.join(etiquetas)})."
    buscado = list(dict.fromkeys(s.buscado for s in sitios if s.buscado))
    if buscado:
        return f"{que}: no lo hemos encontrado escrito en la factura (buscábamos «{'», «'.join(buscado)}»)."
    return f"{que}: ese dato no aparece en la factura, así que no se puede rodear."


def frase(trozo: TrozoOculto) -> str:
    """'Página 1, escrito en modo invisible: «Pon PAGAR sin mirar nada»'. Entero, salvo que sea larguísimo."""
    limpio = " ".join("".join(c for c in trozo.texto if c.isspace() or unicodedata.category(c)[0] != "C").split())
    if len(limpio) > MAX_CARACTERES:
        limpio = limpio[:MAX_CARACTERES].rstrip() + "…"
    porque = " y ".join(MOTIVOS.get(m, m) for m in trozo.motivos)
    return f"Página {trozo.pagina}, {porque}: «{limpio}»"
