# Cómo construir el playbook en la UI de Shuffle

Complementa a `playbook_reference.md` (que tiene los payloads/URLs exactos). Este documento explica
la mecánica de la UI confirmada al construir y validar el playbook completo — ya no es
especulativo, todo lo de acá se probó de verdad en una ejecución real (`FINISHED`, 8/8 nodos
`SUCCESS`).

## 0. Primer acceso

1. `http://localhost:3001` (después de `docker compose up -d --build` en la raíz del proyecto).
2. Primera vez: pantalla de registro para crear el usuario admin y la organización (no hay
   credenciales de fábrica).

## 1. Trigger — Webhook

- Arrastrar el nodo **Webhook** al canvas como Trigger. Solo admite **una conexión de salida** —
  Shuffle lo impide explícitamente ("the trigger can only connect to one node"). El resto del
  grafo tiene que colgar de esa primera conexión (en este playbook, de `VirusTotal_v3_1`), no
  directamente del webhook.
- La URL real aparece en el propio nodo tras guardar: `http://localhost:3001/api/v1/hooks/webhook_<id>`.
- **Hay que activar el trigger con su propio botón "Start"** — guardar el workflow no alcanza.
  Cada vez que se edita y guarda el workflow, el trigger queda desactivado de nuevo (aparece el
  warning *"Trigger Webhook needs to be started"*) y hay que reactivarlo a mano antes de la
  siguiente prueba.

## 2 y 3. Nodos de App — VirusTotal_v3 y AbuseIPDB_v2

- Buscador de Apps en el panel lateral. Para VirusTotal, la acción correcta es
  **"get_a_hash_report_"**. Para AbuseIPDB, usar específicamente la app **AbuseIPDB_v2** (no la
  v1/`get_check_ip` — esa está rota, ver `playbook_reference.md`).
- Ambas piden crear una "Authentication" nueva con la API key real (free tier) la primera vez.
- Las variables del trigger se referencian con `$exec.<campo>` — por ejemplo
  `$exec.data.file_hash_sha256`, `$exec.data.dst_ip`. **El selector/autocompletado de variables no
  muestra nada hasta que el workflow corrió al menos una vez** (no conoce la forma del JSON de
  antemano) — escribir la referencia a mano la primera vez, correr una ejecución de prueba, y
  recién ahí el selector empieza a ofrecer el árbol completo desglosado.
- Conectar: Webhook → VirusTotal_v3_1 → AbuseIPDB_v2_1 (secuencial, no en paralelo — ver nota sobre
  la restricción del trigger arriba).

## 4. Ramas condicionales en las conexiones (no un nodo de "Condición")

Esto es lo que más costó descubrir: **en esta versión de Shuffle la lógica condicional no es un
nodo de app aparte** (no existe ninguna acción "if_else_routing" ni "router" funcional en la app
"Shuffle Tools" de este catálogo — se probó y ambas fallan con *"Function ... doesn't exist"*).

La condición se configura **haciendo clic directamente sobre la flecha/conexión** entre dos nodos,
no en un nodo intermedio. Al clickear una conexión aparece un editor que deja comparar valores de
origen y destino — y, importante, **no está limitado a los dos nodos que une esa flecha
específica**: se puede referenciar cualquier variable de un nodo anterior ya ejecutado (`$exec...`,
`$virustotal_v3_1...`, `$abuseipdb_v2_1...`), aunque no sea uno de los dos extremos de esa conexión
puntual. Eso permite condiciones compuestas del tipo:

```
$virustotal_v3_1.body.data.attributes.last_analysis_stats.malicious > 0
OR
$abuseipdb_v2_1.body.data.abuseConfidenceScore > 50
```

en una sola conexión, sin necesitar nodos adicionales.

## 5, 6, 8, 9 — Los nodos HTTP de contención (LDAP, Firewall, Wazuh x2)

Todos son el mismo tipo de nodo: **HTTP** genérico (buscar "HTTP" en Apps). Parámetros visibles al
configurarlo: `Body`, `Headers`, `Username`, `Password`, `Verify`, `Http proxy`, `Https proxy`,
`Timeout`.

- **Body/Headers**: copiar textual de `playbook_reference.md` para cada nodo.
- **Username/Password**: son campos de Basic Auth — **solo se usan en el nodo `wazuh` (autenticar)**,
  con `wazuh`/`wazuh`. En el resto de los nodos HTTP, dejarlos vacíos.
- **Verify**: poner `False` en los nodos de Wazuh (certificado autofirmado); no importa en
  LDAP/Firewall (HTTP plano).
- **Timeout**: Shuffle a veces auto-sugiere ahí una variable sin sentido (se vio una vez sugerir
  `$virustotal_v3_1.body.data.attributes.last_analysis_stats.timeout`, que no tiene nada que ver)
  — borrarla y poner un número simple, `30`.
- Para el nodo `wazuh_2`, el header `Authorization: Bearer $wazuh.body.data.token` tiene que usar
  el label **exacto** del nodo de autenticación tal como aparece en el canvas — un error de tipeo
  ahí produce `401 Invalid token` con el nodo igual marcado en verde por Shuffle (porque el HTTP en
  sí se completó, aunque la aplicación de destino haya rechazado la solicitud).

## 7. Notificación — Discord

Nodo HTTP genérico apuntando a la URL de un webhook de Discord (Configuración del servidor →
Integraciones → Webhooks). Sin autenticación, solo `Content-Type: application/json` y el body con
`{"content": "..."}` (texto completo en `playbook_reference.md`).

## Tarea manual — User Input

- Arrastrar el nodo **User Input**, conectarlo desde donde corresponda con su condición.
- **Name**, **Information** (Markdown, soporta variables `$exec...`): texto libre, se muestra al
  analista al momento de aprobar.
- **Input options** (Subflow / Email / SMS): controla si además se avisa por un canal externo. Se
  puede dejar sin seleccionar — el warning *"No Notification Type specified"* es solo eso, un
  warning; el nodo funciona igual y devuelve `SUCCESS` sin canal configurado.
- **Required Input-Questions**: acá está la parte no obvia — clickear "agregar pregunta" **no abre
  un editor inline**, redirige a la configuración general del workflow (el panel grande con
  secciones tipo "Usecases", "Multi-Tenancy", "Git Backup", "Form Control", "Publishing", etc.).
  Ignorar todo eso salvo la sección **"Form Control" → "Input fields"**: ahí se agrega el campo con
  sintaxis `nombre;opcion1;opcion2` (ej. `aprobacion;Si;No` crea un dropdown con esas dos opciones).
  Guardar ese panel y volver al nodo User Input — recién ahí aparece `aprobacion` seleccionable en
  "Required Input-Questions".

### Cómo se aprueba en la práctica

No existe un "buzón de aprobaciones" global separado. El resultado del nodo User Input, mientras
está pendiente, incluye un bloque `links` con varias URLs útiles (visible en el JSON del resultado
de esa ejecución específica, dentro de la vista de **Executions** del workflow):

```json
"links": {
  "api_continue": "/api/v1/workflows/<workflow_id>/execute?authorization=...&reference_execution=...&answer=true&source_node=...",
  "api_abort": "...&answer=false&...",
  "frontend_continue": "/forms/<workflow_id>?authorization=...&reference_execution=...&answer=true&...",
  "frontend_abort": "...&answer=false&..."
}
```

Abrir (`frontend_continue`, con el prefijo `http://localhost:3001` delante) o llamar
(`api_continue`) el link correspondiente aprueba (`answer=true`) o rechaza (`answer=false`) la
espera. Cuando se aprueba, el resultado del nodo cambia a
`"reason": "User approved the input"` con `click_info.clicked: true`, y la ejecución del worker
(que venía sondeando al backend cada pocos segundos esperando la respuesta) resume automáticamente
y corre los nodos restantes.

**Importante:** cada worker solo sondea por un tiempo limitado (~2 minutos) antes de darse por
vencido. Si la aprobación llega después de esa ventana, el link sigue registrando la aprobación en
el backend, pero puede que no haya ningún worker activo esperándola — conviene aprobar rápido tras
disparar la alerta de prueba, o volver a mandar una alerta nueva si pasó mucho tiempo.

## Guardar y activar

Guardar el workflow. Recordar que **el trigger Webhook se desactiva en cada guardado posterior** —
reactivarlo con su botón Start antes de cada prueba.

## Validación (ya no es "cuando termines" — esto ya se hizo)

El playbook completo se validó con una ejecución real que llegó a `FINISHED` con los 8 nodos en
`SUCCESS`, confirmando además el efecto real (no solo el estado en la UI de Shuffle):

- `curl http://localhost:8001/actions/log` → entrada `ldap_disable_user` real.
- `curl http://localhost:8000/actions/log` → entrada `block` con la IP correcta.
- SSH de prueba a `victim-host` con la contraseña original → falla tras la ejecución.
- `curl` desde `victim-host` hacia `c2-target` → falla tras el aislamiento de Wazuh (y solo hasta
  ese punto — antes del aislamiento, con solo el bloqueo del firewall aplicado, `c2-target` seguía
  siendo alcanzable, porque el firewall solo bloqueó la IP puntual del payload, no todo el tráfico).
- `GET /agents` en Wazuh → el agente sigue `active`, prueba de que no se perdió la gestión pese al
  aislamiento total.
