import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# Carga las variables de entorno desde el .env de la raíz del repo.
# Se cargan a nivel de proceso, por lo que están disponibles en todos los
# módulos que se importen después de este punto (incluido api.py).
load_dotenv()

# Directorios del proyecto
PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Configuración del logging a nivel de aplicación. Para obtener el logger en
# cada módulo se debe llamar a logging.getLogger("geoyield_api"), lo que
# permite un control centralizado del nivel de log a través de la variable
# de entorno LOG_LEVEL, sin tocar código.
log_level = int(os.getenv("LOG_LEVEL", "20"))  # 20 = INFO por defecto
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_DIR / "geoyield_api.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("geoyield_api")

if __name__ == "__main__":
    # El autoreload solo tiene sentido en desarrollo local; en producción
    # (Docker/Render) debe estar desactivado. Se controla con ENV en vez de
    # dejarlo fijo en True, que era el bug original.
    is_dev = os.getenv("ENV", "development") == "development"

    uvicorn.run(
        "backend.api.api:app",
        host="0.0.0.0",
        port=8000,
        log_level=log_level,
        reload=is_dev,
    )
