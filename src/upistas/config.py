"""Configuración leída del entorno (.env en local, variables en despliegue)."""
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # Base de datos del estado del pipeline (DBOS). SQLite en local; Postgres para escalar.
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'upistas.sqlite').as_posix()}")
    caja_dir: Path = Path(os.getenv("CAJA_DIR", ROOT.parent / "caja"))
    erp_url: str = os.getenv("ERP_URL", "http://127.0.0.1:8009")
    erp_user: str = os.getenv("ERP_USER", "alberto")
    erp_password: str = os.getenv("ERP_PASSWORD", "FACTURAS2009")
    helmcode_api_key: str = os.getenv("HELMCODE_API_KEY", "")
    helmcode_base_url: str = os.getenv("HELMCODE_BASE_URL", "https://api.helmcode.com/v1")
    modelo_vision: str = os.getenv("MODELO_VISION", "qwen3.6")
    modelo_texto: str = os.getenv("MODELO_TEXTO", "glm5.3")
    concurrencia: int = int(os.getenv("CONCURRENCIA", "16"))
    outputs_dir: Path = ROOT / "outputs"
    # Fecha de referencia para "no futura". Fijarla (HOY=2026-09-18) hace los resultados reproducibles.
    hoy: date | None = date.fromisoformat(os.environ["HOY"]) if os.getenv("HOY") else None


settings = Settings()
