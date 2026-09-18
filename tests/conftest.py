import os
import tempfile
from pathlib import Path

# DBOS lee DATABASE_URL al importar el pipeline: cada sesión de tests usa su propia SQLite.
_tmp = Path(tempfile.mkdtemp(prefix="upistas-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.sqlite').as_posix()}"
