# ==============================================================================
# DOCKERFILE DE LA API (Backend)
# ==============================================================================
# Este archivo define cómo se construye la imagen de nuestra aplicación FastAPI.
# Elegimos la versión "slim" (reducida) de Python 3.12 porque elimina librerías 
# del sistema operativo que no necesitamos, haciendo que el contenedor sea 
# más ligero, rápido de descargar y con menor superficie de ataques de seguridad.
FROM python:3.12-slim

# Ajustes obligatorios para ejecutar Python dentro de contenedores:
# 1. PYTHONUNBUFFERED=1: Fuerza a que los logs (prints y system logs) salgan 
#    por pantalla de inmediato sin quedarse atascados en la memoria intermedia.
# 2. PYTHONDONTWRITEBYTECODE=1: Evita que Python genere archivos basura (.pyc) 
#    en el disco duro, manteniendo la imagen limpia.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Definimos el directorio de trabajo interno del contenedor
WORKDIR /app

# Instalamos poppler-utils (pdftotext) para la extracción de PDFs normativos (RAG)
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------------------
# OPTIMIZACIÓN DE PESO Y ESPACIO EN DISCO (PyTorch CPU-Only)
# ------------------------------------------------------------------------------
# sentence-transformers requiere 'torch'. Por defecto en Linux, pip descarga la 
# versión de PyTorch con soporte completo NVIDIA CUDA / cuDNN / Triton (más de 5 GB).
# En servidores e instancias EC2 sin GPU (CPU-only), esto satura el disco duro y 
# ralentiza el build. Instalando explícitamente la rueda oficial CPU de PyTorch, 
# el paquete pasa de 5.500 MB a apenas 180 MB (un 97% menos).
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# ------------------------------------------------------------------------------
# ESTRATEGIA DE CACHÉ DE CAPAS (Layer Caching)
# ------------------------------------------------------------------------------
COPY backend/requirements.txt ./backend/requirements.txt

# Instalamos las librerías restantes.
RUN pip install --no-cache-dir -r backend/requirements.txt

# Una vez instaladas las dependencias, copiamos el resto del código fuente.
COPY backend/ ./backend/
COPY database/ ./database/
COPY scripts/ ./scripts/

# Documentamos que internamente nuestra API trabaja por el puerto 8000.
EXPOSE 8000

# Lanzamos el servidor usando nuestro entrypoint principal (main.py).
CMD ["python", "-m", "backend.api.main"]
