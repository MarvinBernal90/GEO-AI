# ADR 0001: Motor de base de datos vectorial — pgvector vs. Qdrant

**Estado:** Aceptada (Fase 0). Sigue vigente: los embeddings viven en `legal_chunks` con un índice HNSW coseno.

## Contexto

El motor RAG legal necesita almacenar y consultar embeddings de fragmentos de normativa urbanística (PGM y leyes generales). Se evaluaron dos opciones:

1. **PostgreSQL + pgvector**, en la misma instancia Postgres/PostGIS que ya aloja los datos sociodemográficos y geoespaciales.
2. **Qdrant**, como base de datos vectorial dedicada.

## Decisión

Usar **pgvector sobre la misma base Postgres/PostGIS**.

## Justificación

- **El valor diferencial es cruzar normativa (vectorial) con geografía y demografía (relacional/espacial).** Con pgvector una sola consulta SQL combina filtros por zona o espaciales con similitud semántica. Con Qdrant habría que orquestar dos sistemas y sincronizar identificadores.
- **PostGIS ya es una dependencia dura**, así que la base de datos existe de todas formas.
- **Volumen:** el corpus de una ciudad piloto son miles de chunks, no millones. HNSW rinde de sobra a esa escala; los problemas que resuelve Qdrant (escala muy alta, QPS elevado, filtrado avanzado) no existen todavía.
- **Menos infraestructura:** un equipo de 4 personas opera una única base de datos (provisión, copias, seguridad) en vez de dos.

## Consecuencias

- La extensión se habilita con `CREATE EXTENSION IF NOT EXISTS vector;`. La imagen oficial `postgis/postgis` no la incluye, por eso `deployment/Dockerfile.postgis` parte de `postgres:18` e instala PostGIS y pgvector desde PGDG. RDS soporta ambas ([aws-rds-migration.md](../aws-rds-migration.md)).
- La dimensión del vector (1024, Titan V2) está fijada por la migración `0006_titan_embeddings_dim`; cambiar de modelo de embeddings exige una migración y reindexar el corpus.
- Los embeddings comparten recursos con el tráfico transaccional y geoespacial. Hoy no es un problema; si lo fuera, es la señal para revisar esta decisión.

## Cuándo revisarla

Migrar a una base vectorial dedicada si ocurre alguno de estos casos:

- El corpus escala a varias ciudades y alcanza millones de chunks.
- Se necesitan latencias de recuperación muy bajas a alta concurrencia.
- Se necesita filtrado avanzado sobre payloads o cuantización que pgvector no ofrece.
- El escalado del motor vectorial debe desacoplarse de la carga transaccional/geoespacial.
