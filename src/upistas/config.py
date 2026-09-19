"""Configuración leída del entorno (.env en local, variables en despliegue)."""
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _url_por_defecto() -> str:
    return f"sqlite:///{(ROOT / 'upistas.sqlite').as_posix()}"


def ruta_sqlite(url: str) -> Path:
    """`sqlite:///C:/x/y.sqlite` o `sqlite:////home/x/y.sqlite` → ruta del fichero."""
    ruta = unquote(urlparse(url).path).lstrip("/")
    if not (len(ruta) > 1 and ruta[1] == ":"):  # sin letra de unidad: ruta POSIX absoluta
        ruta = "/" + ruta
    return Path(ruta)


def url_dbos(url: str) -> str:
    """Dónde guarda DBOS su estado.

    En Postgres comparte servidor y base con la app (DBOS usa su propio esquema `dbos`).
    En SQLite usa un fichero hermano: dos escritores sobre el mismo fichero se bloquean.
    """
    if url.startswith("sqlite"):
        ruta = ruta_sqlite(url)
        return f"sqlite:///{ruta.with_suffix('.dbos' + ruta.suffix).as_posix()}"
    return url


def base_de_datos_django(url: str) -> dict:
    """La misma DATABASE_URL, en el formato que entiende Django."""
    if url.startswith("sqlite"):
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(ruta_sqlite(url)),
            "OPTIONS": {"timeout": 20, "init_command": "PRAGMA journal_mode=WAL;"},
        }
    u = urlparse(url)
    if u.scheme not in ("postgresql", "postgres"):
        raise ValueError(f"DATABASE_URL no soportada: {u.scheme}. Usa sqlite:/// o postgresql://")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"),
        "USER": unquote(u.username or ""),
        "PASSWORD": unquote(u.password or ""),
        "HOST": u.hostname or "localhost",
        "PORT": u.port or 5432,
        "CONN_MAX_AGE": 60,
    }


@dataclass(frozen=True)
class Settings:
    # Una sola base de datos para todo: la app (Django) y el estado de los workflows (DBOS).
    # Por defecto SQLite en la raíz del repo; para escalar, postgresql://usuario:clave@host/base.
    database_url: str = os.getenv("DATABASE_URL", _url_por_defecto())
    caja_dir: Path = Path(os.getenv("CAJA_DIR", ROOT.parent / "caja"))
    erp_url: str = os.getenv("ERP_URL", "http://127.0.0.1:8009")
    erp_user: str = os.getenv("ERP_USER", "alberto")
    erp_password: str = os.getenv("ERP_PASSWORD", "FACTURAS2009")
    helmcode_api_key: str = os.getenv("HELMCODE_API_KEY", "")
    helmcode_base_url: str = os.getenv("HELMCODE_BASE_URL", "https://api.helmcode.com/v1")
    modelo_vision: str = os.getenv("MODELO_VISION", "qwen3.6")
    modelo_vision_respaldo: str = os.getenv("MODELO_VISION_RESPALDO", "gemma4")
    modelo_texto: str = os.getenv("MODELO_TEXTO", "glm5.3")
    concurrencia: int = int(os.getenv("CONCURRENCIA", "16"))
    outputs_dir: Path = ROOT / "outputs"
    # Fecha de referencia para "no futura". Fijarla (HOY=2026-09-18) hace los resultados reproducibles.
    hoy: date | None = date.fromisoformat(os.environ["HOY"]) if os.getenv("HOY") else None

    @property
    def dbos_url(self) -> str:
        return url_dbos(self.database_url)


settings = Settings()
