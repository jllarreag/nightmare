# Guía del código

Una sola Lambda en Python, una tabla DynamoDB y una HTTP API. Sin pydantic, sin clases de servicio, sin inyección de dependencias.

## Flujo

```
Navegador ──POST /sessions──────────────────► handler.handler ──► story.start
          ──POST /sessions/{id}/steps───────►                 └─► story.next_step
```

`start`: valida la entrada → `safety.classify` → Nova genera el paso 1 → `safety.output_is_safe` → `db.save`.
`next_step`: `db.load` → valida la elección → Nova genera el paso siguiente → guardrail de salida → `db.save`.
El paso 5 (cierre) usa razonamiento extendido.

## Backend (`backend/src/nightmare/`)

| Fichero | Qué hace |
|---|---|
| `handler.py` | Punto de entrada. Enruta por `routeKey`, lee el body y convierte errores en respuestas HTTP. |
| `story.py` | `start()` y `next_step()`: toda la lógica de la historia, en dos funciones. |
| `ai.py` | `ask(system, user, parse)`: llama a Nova, extrae el JSON y lo valida con `parse`. Reintenta una vez. |
| `safety.py` | `classify()` (guardrail + clasificador de Nova) y `output_is_safe()`. |
| `db.py` | `save`, `load`, `delete` de la sesión en DynamoDB (TTL de 24 h). |
| `models.py` | Constantes del arco, `Step`, `Session`, `Category` y `ApiError`. |
| `prompts.py` | Textos de los prompts. |
| `messages.py` | Mensajes de parada (riesgo, contenido no permitido) y recursos de ayuda. |

### Ideas clave

- **Validar la salida del modelo**: `Step.from_dict(dict)` comprueba el arco (técnica por paso, 2-3 opciones, cierre con aprendizaje y consejo, máximo de palabras). Si algo falla lanza `ValueError` y `ai.ask` reintenta.
- **Un solo tipo de error**: `ApiError(status, code)`. El handler lo convierte en `{"error": code}`. Los errores de AWS dan 429 (limitación) o 503; cualquier otro, 500 sin detalles.
- **Clientes boto3 a nivel de módulo**: Lambda los reutiliza entre invocaciones. No hay `wiring` ni caché.
- **Configuración**: variables de entorno leídas al inicio del módulo (`BASE_REGION`, `TEXT_MODEL_ID`, `GUARDRAIL_ID`, `GUARDRAIL_VERSION`, `SESSIONS_TABLE`).
- **Privacidad**: solo se guarda un resumen anónimo, nunca el texto original. No se registran cuerpos ni mensajes de excepción.

### Respuestas

```json
{"status": "ok", "session_id": "...", "step": {...}, "finished": false}
{"status": "stopped", "category": "risk", "message": "...", "resources": [...]}
{"error": "language"}
```

## Infra (`infra/`)

- `stacks/nightmare_stack.py`: tabla, Lambda, permisos IAM y API en un único stack. El código se sube con `Code.from_asset("backend/src")`, sin Docker.
- `stacks/guardrail.py`: el Guardrail de Bedrock. El topic `SelfHarm` se convierte en `risk`.

## Comandos

```powershell
cd backend; .venv\Scripts\python -m pytest -q      # tests
cd infra;   .venv\Scripts\python -m pytest -q      # tests de infra
cd infra;   npx aws-cdk synth                      # plantilla
cd infra;   npx aws-cdk deploy                     # despliegue
```

## Pendiente (no implementado todavía)

Imágenes (Stability), voz (Polly) y galería. Se añadirán como funciones nuevas en `story.py`/ficheros propios, reutilizando `ai.ask` y `safety`.
