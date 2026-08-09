# GEO-YIELD-AI

**Geo-Yield-AI** es una plataforma SaaS de *Location Intelligence* diseñada para transformar la toma de decisiones en la expansión de cadenas de retail, negocios, franquicias y consultoras inmobiliarias.

Utilizamos un enfoque de **Agente de IA Autónomo** que combina Big Data de movilidad, análisis sociodemográfico y validación normativa instantánea mediante arquitectura RAG.

> **Estado del proyecto:** en construcción por fases. Ver [`docs/structure.md`](docs/structure.md) para la estructura vigente del repo y [`docs/adr/`](docs/adr/) para las decisiones de arquitectura tomadas.

## 📖 Tabla de Contenidos
- [Propuesta de Valor](#-propuesta-de-valor)
- [Características Principales](#-características-principales)
- [Stack Tecnológico](#-stack-tecnológico)
- [Arquitectura del Sistema](#-arquitectura-del-sistema)
- [Instalación y Uso](#-instalación-y-uso)
- [DevOps y Despliegue](#-devops-y-despliegue)
- [Equipo](#-equipo)

---

## 💡 Propuesta de Valor

### El Problema
Abrir un nuevo local comercial conlleva un alto riesgo financiero. Las decisiones suelen basarse en intuiciones o estudios de mercado lentos (semanas) y costosos, que a menudo ignoran las complejas normativas urbanísticas locales (PGOU).

### La Solución
**Geo-Yield-AI** actúa como un consultor inmobiliario 360° que reduce el tiempo de evaluación de semanas a segundos:
* **Validación Hiper-Local:** Mapas de calor de afluencia peatonal real.
* **Inteligencia Legal:** Interpretación automática de leyes urbanas para confirmar la viabilidad de licencias.
* **Análisis de Mercado:** Perfilado demográfico y mapeo de la competencia.

---

## ✨ Características Principales

1. **Análisis de Movilidad Dinámica:** Procesamiento de Big Data del **MITMA** (Ministerio de Transportes) para identificar flujos de personas.
2. **Motor RAG Legal:** Uso de **LlamaIndex** y **pgvector** para consultar normativas urbanísticas sin alucinaciones.
3. **Perfilado Sociodemográfico:** Filtros por niveles de renta, edad y densidad de población.
4. **Semáforo de Viabilidad:** Informe ejecutivo (Verde/Ámbar/Rojo) sobre la factibilidad técnica y legal.

---

## 🛠️ Stack Tecnológico

| Capa | Tecnología |
| :--- | :--- |
| **Lenguaje** | Python 3.12 |
| **IA / RAG** | LlamaIndex, OpenAI GPT-4o / Claude 3.5 *(pendiente)* |
| **Backend** | FastAPI |
| **Frontend** | Vue.js (Mapas interactivos) |
| **Base de Datos** | Supabase (PostgreSQL/PostGIS + pgvector) — ver [ADR 0001](docs/adr/0001-pgvector-vs-qdrant.md) |
| **Data Science** | Pandas, GeoPandas |
| **DevOps** | Docker, GitHub Actions, CI/CD |

---

## 🏗️ Arquitectura del Sistema

El flujo de datos sigue una estructura **Cloud-Native**:
1. **Ingesta:** Carga de datasets MITMA, del INE, del GenCAT y PDFs normativos.
2. **Procesamiento:** Normalización con GeoPandas y creación de embeddings.
3. **Orquestación:** FastAPI coordina las peticiones del usuario con el motor RAG.
4. **Veredicto:** El LLM genera un informe basado en el contexto recuperado de la base vectorial.

Ver [`docs/diagram.md`](docs/diagram.md) para el diagrama completo.

---

## 🚀 Instalación y Uso

### Requisitos previos
* Docker y Docker Compose instalados
* Python 3.12
* Claves de API de OpenAI/Anthropic y Supabase (pendiente validar)

### Pasos para ejecución local con Docker (recomendado)

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/TU_USUARIO/pj-geo-yield-ai.git
   cd pj-geo-yield-ai
   ```

2. **Configurar el entorno:**
   ```bash
   cp .env.example .env
   # Edita .env con tus credenciales
   ```

3. **Levantar la API y la base de datos:**
   ```bash
   docker compose -f deployment/docker-compose.yml up --build
   ```
   La API queda disponible en `http://localhost:8080`. Comprueba `GET /health` y `GET /ready`.

4. **Aplicar las migraciones de base de datos** (desde la raíz del repo, con la BD ya levantada):
   ```bash
   pip install -r backend/requirements.txt
   ALEMBIC_DB_HOST=localhost alembic -c database/alembic.ini upgrade head
   ```
   `ALEMBIC_DB_HOST=localhost` sobrescribe el host de `DATABASE_URL` (que
   por defecto apunta a `postgis`, el nombre del servicio dentro de la red
   de Docker, no resoluble desde el host) para poder conectar desde fuera
   del contenedor. El puerto de Postgres está publicado al host en
   `deployment/docker-compose.yml` precisamente para esto.

5. **Cargar los datos** (requiere los CSV de origen en `data/raw/`, ver `backend/etl/config.py` para los nombres esperados):
   ```bash
   PYTHONPATH=. python -m database.load_to_db
   ```

### Ejecución local sin Docker (solo la API)

1. **Instalar dependencias:**
   ```bash
   pip install -r backend/requirements.txt
   ```

2. **Configurar el entorno:**
   ```bash
   cp .env.example .env
   # Cambia el host de DATABASE_URL de "postgis" a "localhost" si la base
   # de datos corre en Docker con el puerto publicado, o apunta a tu propia
   # instancia de Postgres/PostGIS local.
   ```

3. **Ejecutar la aplicación (desde la raíz del repo):**
   ```bash
   python -m backend.api.main
   ```

---

## 🔄 DevOps y Despliegue
Este proyecto aplica los conocimientos de ingeniería adquiridos en el Máster:

- **Contenedores:** Imagen Docker para asegurar que el entorno de desarrollo sea idéntico al de producción.
- **CI/CD:** Pipeline en GitHub Actions (`integrate.yml`) que ejecuta los tests en cada pull request, y despliegue manual (`deploy.yml`) a Render.
- **Observabilidad:** Monitorización básica de latencias y peticiones vía `/metrics`; latencias del LLM se añadirán en la Fase 2-3.

## 👥 Equipo
Proyecto desarrollado por 4 compañeros del Máster en IA, Cloud y DevOps (Pontia):
- Manuel Yerbes García
- Marvin Bernal
- Enmanuel De Oleo
- Claudi Berenguer Sabaté
