# Nightmare Resolver: documento técnico

Qué está construido, cómo funciona y por qué. Para el detalle del código, ver `docs/guia-codigo.md`. Las tareas están en `.kiro/specs/lucid/tasks.md`.

## 1. Estado

Leyenda: ✅ hecho y probado con tests · 🟡 programado, falta desplegar o probar en AWS · ⬜ sin empezar

| # | Funcionalidad | Backend | Infra (CDK) | Probado con AWS real |
|---|---|---|---|---|
| 1 | Estructura del proyecto y CI | ✅ | ✅ | No aplica |
| 2 | Modelos, cliente de Nova y prompts | ✅ | No aplica | 🟡 la versión anterior sí; hay que repetirlo tras la simplificación |
| 3 | Moderación (guardrail + clasificador) | ✅ | 🟡 guardrail definido | 🟡 |
| 4 | Motor de la historia y API | ✅ | 🟡 tabla, Lambda y API definidas | 🟡 |
| 5 | Imágenes (Stability) | ✅ saneado, moderación, Stability, S3, ruta de consulta | 🟡 Lambda `ImageWorker`, bucket privado y permisos definidos | ⬜ cuota de Stability a 0 en `us-west-2` |
| 6 | Voz (Polly) | ⬜ | ⬜ | ⬜ |
| 7 | Galería pública | ✅ publicar (anonimizada y moderada), listar, borrar con token | 🟡 índice `gallery`, 3 rutas, CORS `DELETE` | ⬜ falta probar con Nova real (cuotas de Bedrock a 0) |
| 8 | Alojamiento del frontend (S3 + CloudFront) y WAF | No aplica | 🟡 S3 + CloudFront definidos, sin WAF | ⬜ |
| 9 | Frontend | 🟡 historia de 5 pasos con ilustraciones (consulta periódica), moderación, ES/EN, galería con portada y compartir/borrar (9.4) | No aplica | ⬜ |
| 10 | Pulido, README y vídeo | ⬜ | ⬜ | ⬜ |

**Despliegue:** la API se probó en `alarmaiot` (`eu-south-2`). El destino definitivo es `nightmare-prod` en `eu-west-3` (sección 7).

## 2. Visión general

| Carpeta | Qué es | Lenguaje |
|---|---|---|
| `frontend/` | La web | Angular (TypeScript) |
| `backend/` | La lógica: IA, moderación e historia. Lambda de la API y Lambda de imágenes (mismo código) | Python 3.12 |
| `infra/` | Los recursos de AWS | Python (AWS CDK) |

```mermaid
flowchart LR
  U[Navegador] --> FE[Frontend Angular]
  FE -->|HTTPS| API[HTTP API]
  API --> L[Lambda única]
  L -->|texto| NOVA[Nova 2 Lite<br/>eu-west-3]
  L -->|moderación| GR[Guardrail]
  L --> DB[(DynamoDB)]
  L -->|invocación asíncrona| W[Lambda ImageWorker]
  W -->|prompt saneado| IMG[Stability<br/>us-west-2]
  W --> S3[(S3 privado<br/>eu-west-3)]
  L -->|URL prefirmada| S3
  W --> DB
```

La Lambda de la API nunca espera a la imagen: la pide a `ImageWorker` y el navegador consulta `GET /sessions/{id}/images` hasta que está lista.

## 3. Conceptos básicos

- **Bedrock / Nova 2 Lite**: servicio de AWS y modelo de texto que usamos (`eu.amazon.nova-2-lite-v1:0`). El prefijo `eu.` deja que AWS atienda la petición en cualquier región europea, pero los datos no salen de Europa.
- **Converse**: la operación de Bedrock con la que hablamos con Nova.
- **Razonamiento extendido**: Nova "piensa" antes de responder. Más preciso, pero más caro y lento. Solo lo usamos en el paso de cierre.
- **Guardrail**: filtro de seguridad de Bedrock (sexual, violencia, odio, ataques al prompt y un tema `SelfHarm`).
- **Stability (Stable Image Core)**: modelo de imágenes, solo en `us-west-2` (respaldo: SD3.5 Large). Nunca recibe el texto original del usuario, solo un prompt saneado y moderado.
- **Lambda**: función que se ejecuta solo cuando se la llama.
- **CDK**: describe la infraestructura con Python. `cdk synth` genera la plantilla, `cdk deploy` crea los recursos y `cdk destroy` los borra.

## 4. Backend

### 4.1 Ficheros (`backend/src/nightmare/`)

| Fichero | Qué hace |
|---|---|
| `handler.py` | Entrada de la Lambda. Enruta por `routeKey` y traduce errores a HTTP |
| `story.py` | `start()` y `next_step()` |
| `gallery.py` | `publish()`, `list_stories()` y `delete()` de la galería pública |
| `ai.py` | `ask()`: llama a Nova y valida el JSON de respuesta |
| `safety.py` | Clasificación de la entrada y comprobación de la salida |
| `db.py` | Guardar, leer y borrar sesiones e historias publicadas; listar la galería por el índice `gallery` |
| `models.py` | Arco de 5 pasos, `Step`, `Session` (con `character`), `Category`, `ApiError` |
| `images.py` | Prompt saneado, moderación, Stability, S3, URLs prefirmadas y estado de cada imagen |
| `worker.py` | Entrada de la Lambda `ImageWorker` (genera una imagen y nunca lanza) |
| `prompts.py` | Instrucciones que se envían a Nova |
| `messages.py` | Textos y recursos de ayuda cuando se para la sesión |

No usa pydantic: los datos son `dataclasses` y `Step.from_dict` valida la respuesta del modelo. Así el zip de la Lambda es solo la carpeta `src`, sin dependencias ni Docker.

### 4.2 Flujo de una historia

```mermaid
flowchart TD
  A[POST /sessions] --> B{Longitud 20-2000<br/>e idioma válidos?}
  B -- No --> E1[400]
  B -- Sí --> C[safety.classify]
  C -- risk / not_serious / forbidden --> S[Mensaje de parada<br/>no se guarda nada]
  C -- ok --> D[Nova genera el paso 1]
  D --> F{Guardrail de salida}
  F -- Bloquea --> S
  F -- Pasa --> G[db.save<br/>solo resumen anónimo]
  G --> R[200 paso 1]
```

`POST /sessions/{id}/steps`: carga la sesión, comprueba que la opción exista en el paso actual, genera el paso siguiente (el 5 con razonamiento extendido), lo pasa por el guardrail de salida y guarda. Si el guardrail bloquea, borra la sesión.

### 4.3 Galería (`gallery.py`)

Publicar es opcional y explícito: el frontend muestra una casilla de consentimiento y el body debe llevar `{"consent": true}`.

```mermaid
flowchart TD
  P[POST /sessions/id/publish] --> C{consent = true?}
  C -- No --> E0[400 consent]
  C -- Sí --> S{Sesión terminada<br/>y no publicada?}
  S -- No --> E1[404 / 409]
  S -- Sí --> A[Nova reescribe los 5 pasos<br/>sin nombres, lugares, fechas...]
  A --> V{Mismos pasos y campos?}
  V -- No, tras reintento --> E2[502 generation_failed]
  V -- Sí --> G{Guardrail de salida}
  G -- Bloquea --> E3[422 not_publishable<br/>no se guarda nada]
  G -- Pasa --> D[Guardar STORY#id con hash del token<br/>marcar la sesión como publicada]
  D --> R[200 story_id + delete_token]
```

- **Qué se publica**: solo `title`, `narration`, `learning`, `coping_tip`, `has_image`, `image` (clave S3 `gallery/<id>/<paso>.jpg`, que la lista convierte en URL prefirmada; `null` si la imagen no estaba lista) y el idioma. Nunca el resumen, las opciones elegidas, los prompts de imagen ni el id de sesión.
- **Anonimización**: una llamada a Nova (`prompts.ANONYMIZER_SYSTEM`, temperatura 0,2) cambia nombres, lugares, fechas, edades, oficios y otros datos por palabras genéricas. `parse_anonymized` rechaza la respuesta si cambia el número de pasos o sus números, si deja campos vacíos o si la narración pasa de 120 palabras.
- **Token de borrado**: `secrets.token_urlsafe(32)` (256 bits). Se devuelve una sola vez. En DynamoDB solo se guarda `sha256(token)` y se compara con `hmac.compare_digest`. Al ser aleatorio, no hace falta un KDF lento.
- **Borrar** (`DELETE /gallery/{id}`): el token va en la cabecera `x-delete-token`, no en la URL, para que no quede en logs de acceso. Un id desconocido y un token incorrecto dan la misma respuesta, `404 not_found`.
- **Listar** (`GET /gallery?language=es&limit=6&cursor=...`): consulta el índice `gallery` de más nueva a más antigua y filtra las caducadas (DynamoDB borra por `ttl` con hasta ~48 h de retraso), así que una página puede traer menos de `limit`. `limit` va de 1 a 20 (6 por defecto). El cursor es el `LastEvaluatedKey` en base64url y solo se acepta si tiene exactamente `pk`, `gpk` y `gsk` del idioma pedido.
- **Una vez por sesión**: `Session.published` evita publicar dos veces (`409 already_published`).

### 4.4 Moderación (`safety.py`)

1. Guardrail sobre la entrada. Si salta el tema `SelfHarm`, es `risk` sin más.
2. Clasificador de Nova: `ok`, `not_serious`, `forbidden_content` o `risk`. `risk` siempre gana.
3. Si el guardrail bloqueó y el clasificador no dijo `risk`, el resultado es `forbidden_content`.
4. Sin `GUARDRAIL_ID` configurado, el guardrail se omite (útil en local).
5. Imágenes: el prompt visual se modera antes de salir a `us-west-2` (sección 4.5).

En una versión anterior se repetía la clasificación con razonamiento extendido antes de rechazar. Se quitó por simplicidad. La lista de palabras prohibidas para los prompts de imagen ha vuelto con las imágenes (`IMAGE_BLOCKLIST`, tarea 3.4). Es deliberadamente estricta porque un falso positivo solo cuesta una ilustración; hay que comprobar con casos reales que no descarta demasiadas pesadillas oscuras genuinas.

### 4.5 Imágenes (`images.py`, `worker.py`)

Hay dos imágenes por historia: el paso 1 y el final reescrito (paso 4). Los pasos 2, 3 y 5 reutilizan la última imagen lista de un paso anterior.

```mermaid
flowchart TD
  A[Se guarda el paso 1 o 4] --> B[Item IMAGE# pending + invocar ImageWorker]
  B --> C[Nova: escena genérica en inglés]
  C --> D{Lista negra, guardrail OUTPUT<br/>y veredicto de Nova}
  D -- No --> F[status failed]
  D -- Sí --> E[Prompt + personaje + sufijo de estilo -> Stability]
  E -- ClientError --> E2[SD3.5 Large]
  E -- ok / E2 ok --> G[S3 sessions/sid/paso.jpg, status ready]
  E2 -- falla o filtrada --> F
```

Decisiones y compromisos:

| Tema | Decisión | Compromiso |
|---|---|---|
| Quién genera | Segunda Lambda `ImageWorker` (mismo código, 60 s, sin reintentos), invocada con `InvocationType=Event` | Nova + Stability tardan 15-40 s y no caben en los 29 s de la API. Se rechazó auto-invocar la misma Lambda (dependencia circular en CDK) y SQS o Step Functions (más piezas). Sin reintentos para no duplicar llamadas de pago |
| Cuándo | Las dos imágenes son asíncronas; ninguna bloquea la respuesta | El texto del paso 1 aparece unos segundos antes que su imagen (marcador de posición) |
| Imagen final | Empieza cuando se guarda el paso 4, mientras la persona lo lee | El prompt depende de las elecciones; generarla desde el paso 1 podría ilustrar un final que la narración no cuenta. El requisito 4.4 es SHOULD y se lee así |
| Cómo se entera el navegador | Consulta cada 4 s a `GET /sessions/{id}/images` (máximo 15 intentos) | Sin WebSocket ni SSE (más infraestructura). El límite global de 5 rps desaconseja intervalos menores. Pasados los intentos se muestra el bloque neutro |
| Almacenamiento | Un bucket S3 privado en `eu-west-3` y URLs prefirmadas de 1 h; DynamoDB guarda claves, no URLs | Sin CDN ni caché, y las URLs cambian en cada llamada: una galería abierta durante horas tiene URLs caducadas hasta recargar. CloudFront con OAC se descartó por el ciclo entre stacks y porque las cachés de borde conservarían imágenes borradas |
| Duración | Sesión: `sessions/` caduca a 1 día. Publicada: se **copia** a `gallery/<story_id>/` (caduca a `GALLERY_TTL_DAYS + 1` días) y se borra con la historia | Copiar evita que borrar o caducar una sesión rompa una historia publicada, y al revés. Solo se copian imágenes `ready` |
| Coherencia | Nova devuelve un `character` genérico en el paso 1; ambas imágenes usan `personaje. escena. sufijo` y la misma semilla derivada del id de sesión | Si falta `character`, solo escena + sufijo |
| Moderación | Falla cerrado: cualquier fallo da `failed`, nunca se llama a Stability y nunca se rompe la historia | Se pierde alguna ilustración válida a cambio de no enviar nada dudoso |

Entorno: `IMAGE_BUCKET`, `IMAGE_WORKER_FUNCTION` (API) y `IMAGE_BUCKET`, `IMAGE_REGION`, `IMAGE_MODEL_ID`, `IMAGE_FALLBACK_MODEL_ID` (worker; los modelos y la región son constantes en `nightmare_stack.py`). Si falta `IMAGE_WORKER_FUNCTION` o `IMAGE_BUCKET`, pedir una imagen no hace nada y las historias funcionan sin ilustraciones.

Ruta: `GET /sessions/{session_id}/images` devuelve `{"images": {"1": {"status": "ready|pending|failed", "url": "..."|null}, "4": {...}}}` solo para los pasos con imagen. Una sesión desconocida da `404 session_not_found`; un item `IMAGE#` ausente cuenta como `failed`.

Frontend: imagen lista con texto alternativo, marcador pulsante mientras está pendiente y bloque neutro con un mensaje cálido si falla. Los errores de la consulta nunca se muestran. Las animaciones son CSS y respetan `prefers-reduced-motion`.

Nota: mientras las cuotas de Stability en `us-west-2` sigan a 0, no se puede probar con AWS real; los tests simulan todo.

### 4.6 Errores

| Situación | Respuesta |
|---|---|
| Idioma, longitud, opción o body inválidos | 400 con `{"error": código}` |
| Sesión inexistente o caducada | 404 `session_not_found` |
| Sesión ya terminada | 409 `session_finished` |
| Publicar sin consentimiento | 400 `consent` |
| `limit` o `cursor` inválidos en la galería | 400 `limit` / `cursor` |
| Publicar una historia sin terminar o ya publicada | 409 `session_not_finished` / `already_published` |
| El texto anonimizado no pasa el guardrail | 422 `not_publishable` |
| Borrar con id o token incorrectos | 404 `not_found` |
| El modelo no devuelve un JSON válido tras un reintento | 502 `generation_failed` |
| Throttling de AWS | 429 `busy` |
| Otro error de AWS | 503 `unavailable` |
| Cualquier otro | 500 `internal`, sin detalles |

No se registran cuerpos de petición ni mensajes de excepción, porque pueden contener texto del usuario.

### 4.7 Privacidad

- El texto original solo vive en memoria durante la petición. Se guarda un resumen anónimo generado por Nova.
- Las sesiones caducan a las 24 h (campo `ttl`).
- Solo sale de la UE un prompt de imagen saneado y moderado (sin nombres ni lugares, sin el texto original), hacia `us-west-2`. La imagen generada se guarda en `eu-west-3`. El worker nunca ve el texto original: la sesión solo guarda el resumen anónimo.
- Las imágenes de sesión caducan a 1 día; las publicadas, con la historia o al borrarla. No se registran prompts, escenas ni narraciones, solo ids, paso y estado.
- Nada es público por defecto. Publicar pide consentimiento explícito, pasa por la anonimización de Nova y por el guardrail de salida.
- Las historias publicadas caducan a los 90 días (`GALLERY_TTL_DAYS`) o cuando la persona las borra con su enlace privado.
- El token de borrado solo existe en la respuesta y en el enlace. El backend guarda su hash y el índice de la galería no lo proyecta.
- El enlace de borrado usa el fragmento (`#/delete/<id>/<token>`), que el navegador no envía a CloudFront, y la API recibe el token en una cabecera. Tras borrar, el frontend quita el token de la barra de direcciones.
- Los logs de la galería solo llevan el id de la historia y el número de pasos.
- Limitación: la anonimización es automática y puede fallar. La interfaz avisa de que hay que leer la historia antes de compartirla; no hay vista previa del texto anonimizado.

## 5. Infraestructura (`infra/`)

### 5.1 Recursos (`stacks/nightmare_stack.py`)

| Recurso | Cantidad | Para qué |
|---|---|---|
| Guardrail y su versión | 1 + 1 | Moderación |
| Tabla DynamoDB | 1 | Sesiones e historias publicadas, con TTL e índice `gallery` (`gpk`, `gsk`, proyección INCLUDE sin `token_hash`) |
| Función Lambda | 2 | `NightmareFunction`: toda la API. `ImageWorker`: genera imágenes (60 s, sin reintentos) |
| Bucket S3 de imágenes | 1 | Privado, cifrado, solo SSL; `sessions/` caduca a 1 día y `gallery/` a `GALLERY_TTL_DAYS + 1` |
| HTTP API, etapa, 6 rutas | 1 | Entrada desde Internet: `POST /sessions`, `POST /sessions/{session_id}/steps`, `GET /sessions/{session_id}/images`, `POST /sessions/{session_id}/publish`, `GET /gallery`, `DELETE /gallery/{story_id}` |

Decisiones:
- **ARM64, 512 MB, 29 s.** La HTTP API corta a los 30 s, y las llamadas a Bedrock tienen un límite de 20 s.
- **Límite global**: 5 peticiones por segundo con picos de 10. El límite por IP llegará con WAF (tarea 8).
- **CORS**: por defecto `http://localhost:4200`. Para otro origen: `cdk deploy -c allowedOrigins='["https://..."]'`. Métodos `GET`, `POST` y `DELETE`; cabeceras `content-type` y `x-delete-token`.
- **Variables de la galería**: `GALLERY_INDEX=gallery` y `GALLERY_TTL_DAYS=90` (constante en `nightmare_stack.py`; `0` = permanente).
- **La tabla se borra con `cdk destroy`.** Guarda sesiones temporales y la galería, que también caduca.
- **Tag** `application = nightmare` en toda la app (`infra/app.py`).

### 5.2 Permisos mínimos

| Permiso | Recurso |
|---|---|
| `bedrock:InvokeModel` | El perfil `eu.amazon.nova-2-lite-v1:0` y el modelo en regiones `eu-*` |
| `bedrock:ApplyGuardrail` | Solo nuestro guardrail |
| DynamoDB lectura y escritura | Solo la tabla y su índice `gallery` (`grant_read_write_data`) |
| `lambda:InvokeFunction` | Solo `ImageWorker` (API) |
| S3 API | `GetObject` en `sessions/*` y `gallery/*`, `PutObject` y `DeleteObject` en `gallery/*` |
| Worker: DynamoDB `GetItem`/`PutItem`, Nova, `ApplyGuardrail`, S3 `PutObject` en `sessions/*` | Solo lo que necesita |
| Worker: `bedrock:InvokeModel` en `us-west-2` | Solo los dos modelos de Stability (principal y respaldo) |

Como el permiso de Nova solo incluye regiones europeas, AWS rechazaría procesar el texto fuera de Europa.

### 5.3 Guardrail (`stacks/guardrail.py`)

| Filtro | Entrada | Salida | Motivo |
|---|---|---|---|
| Sexual | Alto | Alto | Nunca debe aparecer |
| Violencia | **Bajo** | Medio | Las pesadillas son violentas; el clasificador decide qué es gratuito |
| Odio | Alto | Alto | |
| Insultos | Medio | Alto | |
| Conducta indebida | Medio | Alto | |
| Ataque al prompt | Alto | No aplica | Solo tiene sentido en la entrada |

Además define el tema denegado `SelfHarm`. Su nombre debe coincidir con `SELF_HARM_TOPIC` en `backend/src/nightmare/safety.py`. CDK pasa el id y la versión del guardrail a la Lambda como variables de entorno.

### 5.4 Empaquetado

La Lambda se sube con `Code.from_asset("backend/src")`. No hay `pip install` ni Docker, porque boto3 ya viene en el entorno de Lambda. `cdk synth` y `cdk deploy` funcionan en cualquier equipo con Node y Python.

### 5.5 Regiones

| Región | Uso |
|---|---|
| `eu-west-3` (París) | Todo: Nova, guardrail, tabla, Lambda, API y bucket de la web |
| Global | CloudFront (sirve la web; la API se llama directamente en `eu-west-3`) |
| `us-west-2` (Oregón) | Solo la llamada a Stability con el prompt saneado. Nova Canvas dejó de existir el 30/09/2026 |

### 5.6 Coste

Todo es de pago por uso. Cada historia consume unas 6 llamadas a Nova 2 Lite (clasificación y 5 pasos) más las del guardrail. Como las llamadas a Nova ya no pasan por un perfil de inferencia de aplicación, **el gasto de Bedrock no se puede separar por tag**. Los demás recursos sí llevan `application = nightmare`. Si hace falta separar el gasto de Bedrock, se puede recuperar un perfil de aplicación.

## 6. Tests y calidad

| Archivo | Qué comprueba | ¿Llama a AWS? |
|---|---|---|
| `backend/tests/test_app.py` | Validación de `Step`, paradas de moderación, historia de 5 pasos, rutas y errores HTTP, que un paso inseguro borra la sesión. Galería: consentimiento, historia sin terminar, texto inseguro no se publica, una sola publicación, solo campos permitidos y hash del token, borrado con token correcto e incorrecto, orden y paginación, caducadas ocultas, flujo completo por el handler y una tabla falsa para `db.put_story`/`query_stories` | No (fakes) |
| `backend/tests/test_images.py` | Escena saneada, lista negra, moderación que falla cerrado, Stability con respaldo, S3 y estados, ruta `images`, copia al publicar y borrado | No (fakes) |
| `infra/tests/test_stack.py` | Las dos Lambdas, las 6 rutas, bucket de imágenes, permisos mínimos del worker, TTL de la tabla, índice `gallery` sin `token_hash`, variables de la galería, permisos de Bedrock, tema `SelfHarm`, CORS con `DELETE` y `x-delete-token` | No |
| `backend/tests/test_properties.py` | Tests basados en propiedades (Hypothesis): invariantes del arco de 5 pasos, límites de `Step`, ida y vuelta JSON de `Session`, recursos de ayuda solo en `risk`; cursor de la galería (ida y vuelta, basura, otro idioma), validación de la anonimización y hash del token | No |
| `infra/tests/test_frontend_stack.py` | Bucket privado con OAC, CloudFront con HTTPS, CORS de la API con el dominio de CloudFront | No |
| `frontend/src/app/app.spec.ts` | Formulario, primer paso, elección, parada por riesgo con recursos, errores y reintento; imágenes: consulta a los 4 s, imagen con alt, bloque neutro, errores silenciosos y reutilización en pasos sin imagen | No (HTTP simulado) |
| `frontend/src/app/gallery.spec.ts` | Compartir con consentimiento y enlace de borrado, error `not_publishable`, galería con "cargar más" y estado vacío, enlace de borrado que pide confirmación y envía `x-delete-token`, historia no encontrada, portada con imagen del paso 1 | No (HTTP simulado) |

Resultado actual: 71 tests de backend, 14 de infra y 16 de frontend pasan, `ruff check` y `ruff format --check` están limpios, y `cdk synth` termina sin errores.

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest -q
cd ..\infra; .\.venv\Scripts\python.exe -m pytest -q
$env:CDK_DEFAULT_REGION="eu-west-3"; npx aws-cdk@2.1148.1 synth
cd ..\frontend; npx ng test --watch=false
```

Automatismos:
- **CI en GitHub** (`.github/workflows/ci.yml`): lint y tests del backend, build del frontend, tests de infra y `cdk synth`.
- **Hook de Kiro** (`.kiro/hooks/backend-tests-on-save.json`): lanza los tests al guardar un `.py` del backend.

Pendiente: un corpus de entradas para evaluar el clasificador contra Nova real. El anterior (24 casos) se borró con la simplificación y está en el historial de git.

## 7. Despliegue

### 7.1 Destino

Cuenta **`nightmare-prod` (`639589055085`)**, creada para la app en la OU `nightmare` con `scripts/org-accounts.bat`. Región **`eu-west-3` (París)**. El código no depende de ninguna cuenta: CDK usa la del perfil con el que se despliega.

| Dato | Valor |
|---|---|
| Página SSO | `https://d-9067f1fd59.awsapps.com/start` |
| Región de IAM Identity Center | `us-east-1` |
| Usuario | `jllarreag2022` (`AdministratorAccess`) |
| Perfil | `nightmare-prod` (región `eu-west-3`) |
| Perfil de la cuenta de gestión | `jllarreag-2` (SSO) |

Para renovar la sesión: `aws sso login --sso-session jllarreag-sso`.

### 7.2 Por qué París y no España

En `nightmare-prod`, todas las cuotas de Bedrock en `eu-south-2` aparecían a 0 (también un día después), mientras que en `eu-west-3` tienen los valores por defecto (2000 peticiones/min y 8 M tokens/min para Nova 2 Lite). El perfil `eu.` funciona igual y los datos siguen en la UE. Mientras tanto se probó la API en `alarmaiot` (`eu-south-2`), que se destruye tras migrar.

### 7.3 Pasos

```powershell
aws sso login --sso-session jllarreag-sso
aws sts get-caller-identity --profile nightmare-prod
cd infra
.\.venv\Scripts\Activate.ps1
npx aws-cdk@2.1148.1 bootstrap aws://639589055085/eu-west-3 --profile nightmare-prod --tags application=nightmare   # una vez
npx aws-cdk@2.1148.1 deploy --all --profile nightmare-prod
cd ..
scripts\deploy-frontend.bat nightmare-prod
```

`deploy --all` crea `NightmareResolverWeb` (S3 + CloudFront) y `NightmareResolver` (API). El script del frontend compila la app, escribe `config.json` con la URL de la API, sube los ficheros y muestra la URL de CloudFront (añade `?debug` para ver las respuestas de la API). Para borrar todo: `npx aws-cdk@2.1148.1 destroy --all --profile nightmare-prod`.

Después del despliegue:
- Recorrer una historia completa llamando a la API real.
- Probar las cuatro rutas de moderación (`ok`, `not_serious`, `forbidden_content`, `risk`) con el guardrail activo.
- Confirmar que Nova responde con el perfil `eu.` en la región elegida, incluido el cierre con razonamiento extendido.

## 8. Decisiones

| Tema | Decisión | Motivo |
|---|---|---|
| Simplicidad | Una Lambda, funciones sueltas, sin inyección de dependencias | Es un hackatón: el código debe poder leerse de un tirón |
| Validación | `dataclasses` y `Step.from_dict`, sin pydantic | Sin dependencias, sin Docker, despliegue más simple |
| Modelo de texto | Nova 2 Lite | Barato, disponible en la UE, razonamiento opcional |
| Región | `eu-west-3` (París) | Cuotas de Bedrock disponibles en la cuenta nueva (7.2) |
| Web | S3 privado + CloudFront; la API se llama directamente | El texto de la pesadilla va del navegador a `eu-west-3` sin pasar por CloudFront |
| Modelo de imagen | Stable Image Core en `us-west-2`, respaldo SD3.5 Large | Nova Canvas ya no existe |
| Imágenes | 2 (paso 1 y paso 4), asíncronas con Lambda `ImageWorker`, consulta periódica y S3 privado con URLs prefirmadas | Coste, rapidez y contraste entre pesadilla y nuevo final; ver 4.5 |
| Privacidad | El texto original nunca sale de la UE | Solo viaja un prompt saneado y moderado |
| Concurrencia | Sin bloqueo optimista | Un doble clic en un hackatón no justifica la complejidad |
| Prompts | Instrucciones en inglés, respuesta en el idioma del usuario | Un solo juego que mantener |
| Angular | Versión 21 | Angular 22 exige Node 22.22.3 y hay 22.22.2 |
| Galería: duración | 90 días, configurable con `GALLERY_TTL_DAYS` (`0` = permanente) | Limita el riesgo si la anonimización deja pasar algo y dura lo bastante para la evaluación del hackatón. Pasar a permanente no exige tocar código |
| Galería: anonimización | Una pasada de Nova que reescribe los pasos, validada en código, y después el guardrail de salida | Detecta nombres y lugares en contexto, cosa que no hace una regex. Una política PII en el guardrail compartido afectaría también a la historia |
| Galería: datos | Misma tabla con item `STORY#<id>` y un GSI | Añadir una clave de ordenación obligaría a reemplazar la tabla |
| Galería: token | Aleatorio de 256 bits, se guarda su SHA-256; viaja en cabecera y en el fragmento de la URL | No se puede recuperar desde la base de datos y no queda en logs de acceso |
| Frontend: vistas | Vistas por hash (`#/gallery`, `#/delete/...`) con un servicio `Nav`, sin `@angular/router` | Tres vistas no justifican un router; el fragmento no se envía al servidor |

## 9. Pendiente

**Despliegue**
- [ ] Desplegar en `nightmare-prod` (`eu-west-3`), probar la web y la API real y evaluar el clasificador con el guardrail activo.
- [ ] Después, `cdk destroy --all --profile alarmaiot`.

**Revisiones menores**
- [ ] Comprobar que la CI pasa en GitHub Actions tras la simplificación.
- [ ] Revisar las 16 vulnerabilidades moderadas que avisa `npm install` en `frontend/`.
- [ ] La cuota de Stable Image Core en `us-west-2` está a 0 en `nightmare-prod`: pedir aumento antes de probar las imágenes con AWS real.
- [ ] Tras desplegar, probar una historia completa con imágenes, la lista negra con pesadillas oscuras reales y la copia a `gallery/` al publicar.

**Galería**
- [ ] Probar publicar, listar y borrar contra la API real cuando vuelvan las cuotas de Bedrock (la anonimización llama a Nova).
- [ ] Limitación conocida: si la respuesta de publicar se pierde, el token no se puede volver a emitir y la sesión ya figura como publicada (la historia caduca a los 90 días).

**Tareas del spec sin empezar**: 6 voz, 8 WAF y 10 pulido. El frontend (9) tiene la historia con imágenes (9.2) y la galería (9.4).

## 10. Glosario

| Término | Significado |
|---|---|
| Arco | La estructura fija de 5 pasos de la historia |
| IRT | Imagery Rehearsal Therapy: reescribir el final de la pesadilla y ensayarlo |
| Prompt | Texto de instrucciones que se envía a la IA |
| Inyección de prompt | Intento del usuario de dar órdenes a la IA mediante su texto |
| Stack | Conjunto de recursos de AWS gestionados juntos por CDK |
| TTL | Fecha de caducidad de una fila de DynamoDB; pasada esa fecha, se borra |
| CORS | Regla del navegador sobre qué webs pueden llamar a la API |
| SSO | Inicio de sesión único con credenciales temporales |
| Bootstrap | Preparación que CDK necesita una vez por cuenta y región |
