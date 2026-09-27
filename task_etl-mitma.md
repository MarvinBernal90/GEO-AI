# Tareas para el ETL de Movilidad (MITMA)

Este documento detalla los pasos para construir un ETL robusto para los datos de movilidad del MITMA (viajes intraprovinciales), asegurar su ejecución a través de FastAPI y preparar el entorno para evitar conflictos de puertos en la base de datos.

## 1. Cambio de Puerto de Base de Datos (de 5432 a 5433)

**¿Por qué este cambio?**
Es muy común que en tu equipo, algunos desarrolladores (o herramientas locales que utilicen) ya tengan una instancia de PostgreSQL corriendo en su máquina en el puerto por defecto `5432`. Al levantar el contenedor de Docker de nuestro proyecto, si ese puerto ya está ocupado en la máquina física, Docker no puede vincularlo y devuelve errores de *Connection refused*. 
Para que todo el equipo pueda levantar la base de datos del proyecto sin que choque con lo que ya tengan instalado, configuramos Docker para que el contenedor exponga el puerto `5433` hacia afuera, mientras internamente sigue usando el `5432`.

**Código y cambios a realizar en `.env` (comunícalo a tus compañeros):**
En vuestro archivo `.env` local (el cual no se sube a Git), deben añadir o descomentar estas variables:

```env
# 1. Le dice a Docker que exponga la base de datos al puerto 5433 del ordenador.
POSTGRES_HOST_PORT=5433

# 2. Le dice a los scripts de Python locales (fuera de Docker) a qué puerto conectarse.
DB_PORT_OVERRIDE=5433

# 3. Obliga a los scripts locales a buscar la BD en tu máquina (localhost) en lugar de la red de Docker.
DB_HOST_OVERRIDE=localhost
```
*Nota: Si algún compañero te dice que le sigue dando fallo, recuérdale que tiene que reiniciar los contenedores (`docker compose down` y luego `docker compose up -d`) para que los cambios del `.env` apliquen.*

## 2. Desarrollo del ETL MITMA (`backend/etl/etl_mitma.py`)

Comenzaremos implementando el ETL para los viajes intraprovinciales. Primero, aseguraremos que el script se pueda ejecutar independientemente por consola para facilitar pruebas y desarrollo.

**Tareas:**
- [X] Crear el script `backend/etl/etl_mitma.py`.
- [X] Implementar el uso del logger estructurado de la aplicación usando `backend.observability`.
- [X] Definir la conexión a la base de datos a través de `backend.db.connection`.
- [X] Realizar la ingesta y limpieza con Pandas (aislar los viajes, limpiar columnas, agregar por distrito siguiendo el patrón ya validado en `income.py`).
- [X] Crear el bloque para ejecución manual con sus correspondientes logs visibles en consola:
  ```python
  if __name__ == '__main__':
      # Código para ejecutar
  ```
  Para que lo pruebes así: `python -m backend.etl.etl_mitma`

## 3. Integración en la API (FastAPI y Swagger)

Una vez el ETL funcione por consola, lo expondremos en la API para poder dispararlo desde Swagger (Docs) y, posteriormente, desde el Frontend.

**Tareas:**
- [X] Crear o actualizar un *router* (por ejemplo, `backend/api/routers/etl.py`).
- [X] Crear un *endpoint* `POST /api/etl/mitma` que inicie el proceso.
- [X] Usar *BackgroundTasks* de FastAPI o `async` para que la petición al endpoint no se quede colgada esperando a que el ETL termine (ya que descargar y procesar los datos de MITMA puede ser pesado).
- [X] Implementar una respuesta JSON de confirmación o un mecanismo para leer el progreso/logs del proceso desde Swagger.

## 4. Consumo desde el Frontend (App)

Cuando los datos del MITMA existan en la BD y el ETL sea accesible vía API.

**Tareas:**
- [X] Añadir en el panel de administración o sección del Frontend un botón para llamar al endpoint `POST /api/etl/mitma`.
- [X] (Opcional) Leer la respuesta de éxito para notificar en la interfaz que los datos se están cargando.
- [X] Actualizar los mapas y las vistas del frontal para que soporten la nueva variable de "viajes intraprovinciales" que acabamos de meter.

---
**¿Empezamos?** Ve a tu editor y abre (o crea) el archivo `backend/etl/etl_mitma.py`. Yo te generaré el primer código de esqueleto y limpieza.
