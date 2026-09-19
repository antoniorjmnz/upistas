"""El cliente contra el alberto_erp.py de verdad (se salta si no está La Caja clonada)."""
import socket
import subprocess
import sys
import time

import httpx
import pytest

from upistas.adaptadores.fuentes.erp_http import ClienteErpHttp
from upistas.config import settings

ERP = settings.caja_dir / "alberto_erp.py"
pytestmark = pytest.mark.skipif(not ERP.exists(), reason="La Caja no está clonada en CAJA_DIR")


@pytest.fixture(scope="module")
def erp_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, str(ERP), "--puerto", str(puerto), "--rapido"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{puerto}"
    for _ in range(50):
        try:
            httpx.get(f"{url}/erp/estado", timeout=0.5)
            break
        except httpx.TransportError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(timeout=5)


def test_descarga_los_516_asientos_del_erp_real(erp_url):
    d = ClienteErpHttp(erp_url, "alberto", "FACTURAS2009").descargar()
    assert len(d.asientos) == 516
    assert sum(a.estado == "PAGADA" for a in d.asientos) == 9
    assert sum(not a.nif for a in d.asientos) == 20  # el bloque PO-0538..0557 viene sin NIF
    assert d.lote2_cargado is False
    # El bridge falla una de cada diez consultas: tiene que haberlo absorbido.
    assert d.estadisticas.reintentos_ora >= 2


def test_el_detalle_del_erp_coincide_con_lo_que_sabemos(erp_url):
    d = ClienteErpHttp(erp_url, "alberto", "FACTURAS2009").descargar()
    por_pedido = {a.pedido: a for a in d.asientos}
    assert str(por_pedido["PO-2026-0497"].importe) == "84700.00"
    assert por_pedido["PO-2026-0474"].estado == "PAGADA"
    assert por_pedido["PO-2026-0546"].id == "AS-00507"
