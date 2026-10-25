# Arquitectura y decisiones de diseño

Resumen técnico de Geo-Yield-AI: qué bloques tiene, cómo se conectan y por qué se diseñó así. El diagrama de flujo está en [diagram.md](diagram.md) y la estructura de carpetas en [structure.md](structure.md).

## Bloques

| Bloque | Qué hace | Código |
| :--- | :--- | :--- |
| **Datos** | ETL de renta (INE), movilidad (MITMA) y censo comercial (Open Data BCN) a PostGIS. La vista `district_scorecard` calcula el índice de oportunidad (0-100) de cada distrito | `backend/etl/`, `database/` |
| **RAG legal** | Trocea la normativa por artículo, genera embeddings (Titan V2, 1024 dim), busca por similitud coseno con filtro de zona (el asistente además reordena con Rerank) y genera una respuesta con cita | `backend/rag/` |
| **Agente de viabilidad** | Grafo LangGraph: datos del distrito y normativa de la zona en paralelo, y síntesis final con semáforo | `backend/ia/agent.py` |
| **Chat** | Extrae dirección, distrito y pregunta de una frase libre y reutiliza el mismo pipeline. Con sesión, un asistente ReAct con memoria | `backend/ia/chat_intent.py`, `chat.py` |
| **Geo** | Dirección → coordenadas y distrito (Nominatim) → zona PGM (geoportal AMB) | `backend/geo/` |
| **API y frontend** | FastAPI con SSE; SPA Vue con formulario, mapa, visor de normativa y paneles de métricas | `backend/api/`, `frontend/` |

## Decisiones clave

- **Score determinista.** Los datos MITMA solo llegan a nivel de distrito, así que no hay resolución para entrenar un modelo por local. El score es una función de afluencia, renta y competencia, y vive en una vista SQL para que nunca se desincronice de los datos.
- **pgvector en la misma base que PostGIS.** Permite combinar filtros espaciales o por zona con búsqueda semántica en una sola consulta ([ADR 0001](adr/0001-pgvector-vs-qdrant.md)).
- **Búsqueda híbrida.** Con zona PGM se recuperan los mejores fragmentos de esa zona más los de normativa general, se fusionan y se ordenan por distancia coseno.
- **La zona legal nunca se adivina.** Un distrito abarca varias zonas PGM. Se deduce de la dirección (geoportal AMB) o la elige el usuario; si no hay certeza, el chat pide aclaración (`aclaracion`).
- **El chat no es un agente autónomo.** Es una capa de extracción de intención que alimenta el pipeline ya probado, con intervención humana cuando hay ambigüedad. El asistente ReAct (tres herramientas: normalización de calle, puntuación de oportunidad y consulta normativa) solo se usa con sesión iniciada.
- **LLM detrás de una interfaz común** (`messages.create` / `create_stream`). Bedrock es el proveedor por defecto y Gemini un reemplazo con `LLM_PROVIDER=gemini`, sin tocar los módulos que consumen el LLM.
- **Concurrencia.** Los nodos paralelos del grafo abren su propia sesión de base de datos; compartir una `Session` de SQLAlchemy corrompía el estado.
- **Inyección de dependencias** (`embed_fn`, `llm_client`) para testear sin red ni cuota de API.
- **Migraciones solo hacia delante.** Nunca se edita una migración aplicada (0001-0009).
- **Fallos graciosos.** Redis, métricas y servicios externos fallan en abierto: nunca rompen una respuesta.
- **Privacidad.** La dirección escrita por el usuario no se registra en logs ni en trazas ([observability.md](observability.md)).

## Validación

- **Tests:** unos 450 tests unitarios (`tests/unit_tests`), con regresiones para cada bug real encontrado. Los que necesitan base de datos se saltan si no hay una disponible.
- **Calidad RAG:** conjuntos `dev` (61 preguntas) y `holdout` (28) con métricas de recuperación, fidelidad y abstención ([`evals/README.md`](../evals/README.md)).
- **Pruebas contra infraestructura real.** Muchos bugs solo aparecieron con Postgres, PDFs y modelos reales: una migración que asumía pgvector instalado, un parser que se quedaba con la versión derogada de un artículo, o un `id_global` de 37 caracteres en una columna de 36.

## Estado y siguientes pasos

El despliegue actual es EC2 con Docker Compose (API, PostGIS y Redis), frontend en S3 + CloudFront y logs en CloudWatch. Pendiente o propuesto:

- Migrar la base de datos a RDS ([aws-migration-assessment.md](aws-migration-assessment.md), [aws-rds-migration.md](aws-rds-migration.md)).
- Pasar el CD a OIDC y ECR ([aws-cd-assessment.md](aws-cd-assessment.md)).
- Autenticación real con Cognito ([aws-cognito-assessment.md](aws-cognito-assessment.md)).
- Ampliar el corpus a más zonas del PGM y un recomendador de distrito en el chat.
