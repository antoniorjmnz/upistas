"""El cliente del ERP contra un bridge simulado que falla como el de verdad."""
import httpx
import pytest

from upistas.adaptadores.fuentes.erp_http import ClienteErpHttp
from upistas.puertos import ErrorERP

XML = '<?xml version="1.0" encoding="ISO-8859-1"?>\n'


class BridgeFalso:
    """Imita alberto_erp.py: paginación de 20, XML ISO-8859-1 y averías configurables."""

    def __init__(self, n_asientos=45, ora_cada=0, rate_limit_en=(), caduca_en=(), lote2=False, total_miente=False):
        self.filas = [
            (f"AS-{i:05d}", f"PO-2026-{i:04d}", f"{1000 + i}.{i % 100:02d}".replace(".", ","), "PAGADA" if i % 9 == 0 else "PENDIENTE")
            for i in range(1, n_asientos + 1)
        ]
        self.ora_cada = ora_cada
        self.rate_limit_en = set(rate_limit_en)
        self.caduca_en = set(caduca_en)
        self.lote2 = lote2
        self.total_miente = total_miente
        self.peticiones = 0
        self.consultas = 0
        self.tokens_validos = set()
        self.logins = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.peticiones += 1
        if self.peticiones in self.rate_limit_en:
            return self._error(429, "ERP-429", {"Retry-After": "1"})
        if request.url.path == "/erp/login":
            self.logins += 1
            token = f"tok{self.logins}"
            self.tokens_validos.add(token)
            return self._ok(f"<sesion><token>{token}</token></sesion>")
        if request.url.path == "/erp/estado":
            return self._ok(f"<estado><asientos>{len(self.filas)}</asientos><actualizacion_cargada>{'SI' if self.lote2 else 'NO'}</actualizacion_cargada></estado>")
        token = request.headers.get("X-ERP-Token")
        if token not in self.tokens_validos:
            return self._error(401, "SES-401")
        self.consultas += 1
        if self.consultas in self.caduca_en:
            self.tokens_validos.discard(token)
            return self._error(401, "SES-401")
        if self.ora_cada and self.consultas % self.ora_cada == 0:
            return self._error(500, "ORA-00600")
        pagina = int(request.url.params["pagina"])
        paginas = (len(self.filas) + 19) // 20
        trozo = self.filas[(pagina - 1) * 20 : pagina * 20]
        total = len(self.filas) + (1 if self.total_miente else 0)
        asientos = "".join(
            f"<asiento><id>{a}</id><fecha>08/01/2026</fecha><proveedor>P001</proveedor><nif>B46102331</nif>"
            f"<pedido>{p}</pedido><importe>{imp}</importe><estado>{e}</estado></asiento>"
            for a, p, imp, e in trozo
        )
        return self._ok(f"<respuesta><meta><total>{total}</total><paginas>{paginas}</paginas></meta><asientos>{asientos}</asientos></respuesta>")

    @staticmethod
    def _ok(cuerpo: str) -> httpx.Response:
        return httpx.Response(200, content=(XML + cuerpo).encode("iso-8859-1"), headers={"content-type": "text/xml; charset=ISO-8859-1"})

    @staticmethod
    def _error(status: int, codigo: str, extra=None) -> httpx.Response:
        cuerpo = f"{XML}<error><codigo>{codigo}</codigo><mensaje>x</mensaje></error>".encode("iso-8859-1")
        return httpx.Response(status, content=cuerpo, headers={"content-type": "text/xml; charset=ISO-8859-1", **(extra or {})})


def cliente(bridge: BridgeFalso, esperas: list | None = None) -> ClienteErpHttp:
    return ClienteErpHttp(
        "http://erp", "alberto", "FACTURAS2009",
        transport=httpx.MockTransport(bridge),
        dormir=(esperas.append if esperas is not None else (lambda s: None)),
    )


def test_descarga_completa_y_convierte_formatos():
    d = cliente(BridgeFalso(n_asientos=45)).descargar()
    assert len(d.asientos) == 45
    a = d.asientos[0]
    assert (a.id, a.pedido, str(a.importe), a.fecha.isoformat(), a.estado) == ("AS-00001", "PO-2026-0001", "1001.01", "2026-01-08", "PENDIENTE")
    assert sum(x.estado == "PAGADA" for x in d.asientos) == 5


def test_absorbe_ora_00600_sin_perder_ni_duplicar():
    d = cliente(BridgeFalso(n_asientos=45, ora_cada=2)).descargar()
    assert len({a.id for a in d.asientos}) == 45
    assert d.estadisticas.reintentos_ora >= 2


def test_espera_lo_que_dice_retry_after():
    esperas = []
    d = cliente(BridgeFalso(rate_limit_en={3}), esperas).descargar()
    assert d.estadisticas.esperas_429 == 1
    assert 1.0 in esperas
    assert len(d.asientos) == 45


def test_vuelve_a_identificarse_si_caduca_la_sesion():
    d = cliente(BridgeFalso(caduca_en={2})).descargar()
    assert d.estadisticas.relogins == 1
    assert len(d.asientos) == 45


def test_detecta_si_el_lote_2_esta_cargado():
    assert cliente(BridgeFalso(lote2=True)).descargar().lote2_cargado is True


def test_falla_si_la_descarga_no_cuadra_con_el_total():
    with pytest.raises(ErrorERP, match="incompleta"):
        cliente(BridgeFalso(total_miente=True)).descargar()


def test_se_rinde_si_el_erp_no_se_recupera():
    with pytest.raises(ErrorERP, match="intentos"):
        cliente(BridgeFalso(ora_cada=1)).descargar()


def test_no_pasa_del_ritmo_maximo():
    esperas = []
    c = ClienteErpHttp("http://erp", "a", "b", transport=httpx.MockTransport(BridgeFalso()), dormir=esperas.append, peticiones_por_segundo=8)
    c.descargar()
    assert esperas, "debe espaciar las peticiones para no provocar ERP-429"
    assert all(e <= 1 / 8 + 1e-6 for e in esperas)


def test_si_el_erp_esta_apagado_se_rinde_rapido():
    def apagado(request):
        raise httpx.ConnectError("conexión rechazada", request=request)

    esperas = []
    c = ClienteErpHttp("http://erp", "a", "b", transport=httpx.MockTransport(apagado), dormir=esperas.append)
    with pytest.raises(ErrorERP, match="no responde"):
        c.descargar()
    assert sum(e == 1.0 for e in esperas) == 2  # 3 intentos: 2 esperas de 1 s y se rinde
