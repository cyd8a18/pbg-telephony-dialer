# Ejecutar y probar el proyecto

Esta guía explica cómo ejecutar los tests, iniciar la API y reproducir el escenario de webhooks del prototipo de telefonía.

## 1. Activar el entorno virtual

Desde la carpeta raíz del proyecto `telephony-dialer`:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 2. Instalar las dependencias

Si es la primera vez que se ejecuta el proyecto:

```powershell
pip install -r requirements.txt
```

## 3. Ejecutar los tests

En Windows, crear una carpeta temporal local para evitar problemas de permisos con `pytest`:

```powershell
mkdir .pytest_tmp -ErrorAction SilentlyContinue
python -m pytest -v --basetemp=.pytest_tmp
```

Resultado esperado:

```text
5 passed
```

Los tests verifican:

- Idempotencia ante webhooks duplicados.
- Manejo de eventos fuera de orden.
- Persistencia del estado después de reabrir la conexión.
- Separación entre la línea persistente del agente y las llamadas de clientes.
- Manejo de identidad ambigua en llamadas inbound.

## 4. Ejecutar la API

Iniciar el servidor de FastAPI:

```powershell
uvicorn app.main:app --reload
```

La API estará disponible en:

```text
http://127.0.0.1:8000
```

La documentación interactiva de FastAPI estará disponible en:

```text
http://127.0.0.1:8000/docs
```

## 5. Reproducir los webhooks

Mantener FastAPI ejecutándose y abrir una segunda terminal.

Activar nuevamente el entorno virtual:

```powershell
.\.venv\Scripts\Activate.ps1
```

Ejecutar el script:

```powershell
python scripts/replay_webhooks.py
```

Este script reproduce los eventos sintéticos contenidos en `webhooks.jsonl`.

Durante la ejecución se puede observar cómo el sistema procesa eventos normales y detecta eventos duplicados.

Por ejemplo:

```text
4: client_leg.answered -> processed: True, duplicate: False
3: client_leg.answered -> processed: False, duplicate: True
```

Esto demuestra que un mismo evento lógico no modifica el estado dos veces.

## 6. Consultar el estado del sistema

Abrir:

```text
http://127.0.0.1:8000/docs
```

En Swagger:

1. Abrir `GET /state`.
2. Seleccionar `Try it out`.
3. Seleccionar `Execute`.

Después de reproducir `webhooks.jsonl`, el estado debe representar:

- La línea del agente `A-1` activa.
- `C-101` como llamada outbound completada.
- `C-102` como llamada outbound fallida.
- `I-201` como llamada inbound en estado `ringing`.
- La identidad de `I-201` como ambigua entre `L201` y `L202`.

La línea del agente permanece activa aunque una llamada individual de cliente termine.

## 7. Probar recuperación después de un reinicio

Con el estado ya creado, detener FastAPI:

```text
Ctrl + C
```

Volver a iniciar el servidor:

```powershell
uvicorn app.main:app --reload
```

Consultar nuevamente:

```text
GET /state
```

El estado anterior debe continuar disponible gracias a la persistencia en SQLite.

## 8. Conceptos demostrados

El prototipo se enfoca en cuatro aspectos principales del sistema de telefonía:

### Estado

La línea persistente del agente y las llamadas individuales de los clientes se modelan de forma separada.

### Idempotencia

Los webhooks duplicados son identificados para evitar que el mismo evento lógico sea procesado múltiples veces.

### Eventos fuera de orden

El sistema puede recibir eventos en un orden diferente al orden lógico de la llamada sin depender únicamente del orden de llegada.

### Recuperación

El estado se almacena de forma persistente en SQLite, por lo que puede recuperarse después de reiniciar el proceso.

### Separación de identidades

El sistema diferencia entre:

- La línea del agente.
- Una llamada o `client leg`.
- La identidad del cliente.
- El número telefónico.

Un número telefónico no se considera automáticamente una identidad única. Si un número corresponde a múltiples clientes, el sistema mantiene la identidad como ambigua en lugar de seleccionar uno arbitrariamente.