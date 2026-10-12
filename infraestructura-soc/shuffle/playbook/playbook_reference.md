# Playbook de referencia: Conti — Contención en fase de Exfiltración

**Estado: implementado y validado end-to-end.** Esta es la documentación del playbook realmente
construido en Shuffle y probado con una ejecución real completa (`FINISHED`, 8/8 nodos en
`SUCCESS`, con efecto verificado en LDAP, firewall y Wazuh — no solo en la UI). El análisis del
ataque y las decisiones de diseño detrás de esta estructura están en
`ANALISIS_CONTI_Y_ARQUITECTURA.md` (raíz del proyecto).

Disparador: el punto en el Kill Chain donde el profesor indicó que debe arrancar el playbook —
**Exfiltración**, no antes. Payload de prueba:
`infraestructura-soc/alert-injector/payloads/conti_exfiltration_alert.json`.

## Diagrama final

```
Webhook (Trigger)
   │  (un trigger solo admite 1 conexión de salida)
   ▼
VirusTotal_v3_1  (enriquecimiento por hash)
   │
   ├──────────────────────────────────────────┐
   ▼ (secuencial, siempre)                     ▼ (siempre, sin condición)
AbuseIPDB_v2_1  (enriquecimiento por IP)     firewall — bloquear IOC
   │
   ├──(secuencial, siempre)──▶ Discord_1 — notificación del caso
   │
   ├──(si malicious>0 OR abuseConfidenceScore>50)──▶ ldap — deshabilitar cuenta
   │
   └──(si malicious>0 OR abuseConfidenceScore>50)──▶ Aprobar_Aislamiento (User Input)
                                                          │
                                                          ▼ (secuencial, tras aprobación)
                                                        wazuh — autenticar
                                                          │
                                                          ▼ (secuencial)
                                                        wazuh_2 — aislar host (isolate-host0)
```

El firewall se conecta desde `VirusTotal_v3_1` (no desde el Webhook) porque el Trigger solo admite
una conexión de salida, que ya está usada hacia VirusTotal. Se activa siempre, sin condición —
justificación en la sección 3.2 de `ANALISIS_CONTI_Y_ARQUITECTURA.md` (bajo radio de impacto).

## 1. Trigger — Webhook

- Tipo: **Webhook** (Trigger). Solo admite **una** conexión de salida — el resto del grafo cuelga
  de `VirusTotal_v3_1`, no directamente del webhook.
- La URL real la genera Shuffle en el propio nodo, formato
  `http://localhost:3001/api/v1/hooks/webhook_<id>` (con Shuffle self-hosted, el puerto del
  frontend 3001 también sirve el endpoint del webhook, no hace falta usar el 5001 del backend).
- **Hay que "arrancar" el trigger explícitamente** (botón Start en el propio nodo) — guardar el
  workflow no alcanza. Cada vez que se edita y guarda el workflow después de tenerlo activo, el
  trigger se desactiva de nuevo y hay que reactivarlo a mano antes de la siguiente prueba.
- El body que llega es el JSON completo de `conti_exfiltration_alert.json` (o
  `benign_false_positive_alert.json` para probar la rama de falso positivo).

## 2. Enriquecimiento — VirusTotal_v3_1

- App: **Virustotal_v3** (catálogo de Shuffle) → acción **"get_a_hash_report_"**.
- Campo `id`: `$exec.data.file_hash_sha256`.
- Auth: API key real de VirusTotal (free tier), configurada como "Authentication" de la app.
- **Cuidado con el hash de prueba**: tiene que ser un SHA-256 válido de 64 caracteres hex. Se usa el
  hash real del archivo de prueba EICAR (estándar de la industria antivirus, benigno pero detectado
  por decenas de motores) para tener un resultado "malicioso" reproducible sin manejar malware real:
  `275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f` — verificar con
  `sha256sum` antes de confiar en un hash escrito a mano; un solo carácter mal copiado hace que VT
  responda 400 "Invalid file hash" en vez de darte datos reales.
- Campo real para la condición: `$virustotal_v3_1.body.data.attributes.last_analysis_stats.malicious`
  (cantidad de motores que lo marcaron malicioso — con el hash de EICAR, ~60-66 según el momento).

## 3. Enriquecimiento — AbuseIPDB_v2_1

- App: **AbuseIPDB_v2** — usar específicamente la variante **v2** del catálogo. La acción vieja de
  AbuseIPDB (v1, `get_check_ip` sobre `abuseipdb.com/check/...`) está **rota**: esa API fue dada de
  baja por el proveedor y siempre devuelve 401 "APIv1 has been DEPRECATED". Confirmado en pruebas
  reales — no es un problema de configuración, es que Shuffle todavía cataloga la acción vieja.
- Campo `IP`: `$exec.data.dst_ip`.
- Auth: API key real de AbuseIPDB (free tier).
- Campo real para la condición: `$abuseipdb_v2_1.body.data.abuseConfidenceScore` (0-100).

## 4. Notificación — Discord_1

Conectado desde `AbuseIPDB_v2_1`, **siempre** (sin condición) — se notifica el caso haya o no
enriquecimiento positivo.

- App: nodo **HTTP** genérico (no hace falta una app dedicada de Discord).
- Method: `POST`
- URL: la del webhook de Discord (Configuración del servidor → Integraciones → Webhooks → Nuevo
  Webhook → copiar URL). No necesita autenticación ni headers especiales más que
  `Content-Type: application/json`.
- Body:
  ```json
  {
    "content": "🚨 **Incidente de seguridad detectado — Ransomware Conti (fase Exfiltración)**\n\n**Host afectado:** $exec.agent.name\n**Usuario:** $exec.data.srcuser\n**IP destino (C2/exfiltración):** $exec.data.dst_ip\n**Técnica MITRE ATT&CK:** $exec.rule.mitre.id\n\n**Resultado VirusTotal:** $virustotal_v3_1.body.data.attributes.last_analysis_stats.malicious motores detectaron el hash como malicioso\n**Resultado AbuseIPDB:** score de confianza de abuso = $abuseipdb_v2_1.body.data.abuseConfidenceScore/100\n\nSe iniciaron las acciones de contención automática correspondientes."
  }
  ```

## 5. Contención — LDAP (`ldap`)

Conectado desde `AbuseIPDB_v2_1`, condicional.

- Nodo **HTTP** genérico.
- Method: `POST`
- URL: `http://ldap-wrapper:8001/disable-user` — **se resuelve por nombre de contenedor sin
  problema**, verificado (ver nota de networking abajo).
- Headers: `Content-Type: application/json`
- Body:
  ```json
  { "uid": "$exec.data.srcuser", "reason": "Conti ransomware - fase de exfiltracion detectada (T1567.002)" }
  ```
- **El `uid` tiene que ser un usuario que exista de verdad en el LDAP del laboratorio** — el
  bootstrap solo trae `testuser`. Si el payload usa un nombre distinto (ej. un `srcuser` ficticio
  tipo `svc-backup`), el wrapper devuelve `500 noSuchObject` (el mensaje de error apunta a la OU
  porque `ldap3` reporta el DN padre más profundo que sí existe, no el usuario faltante — confundía
  al principio). Usar `testuser` en el payload de prueba.
- Verificado end-to-end: antes del llamado, `ssh testuser@victim-host` autentica; después, falla.

## 6. Contención — Firewall (`firewall`)

Conectado desde `VirusTotal_v3_1`, **siempre** (sin condición).

- Nodo **HTTP** genérico.
- Method: `POST`
- URL: `http://172.18.0.1:8000/block` — el contenedor `firewall` corre en `network_mode: host`, así
  que no tiene nombre de contenedor resoluble en ninguna red. `host.docker.internal` **no
  resuelve** en este entorno Linux (probado, falla). Lo que sí funciona es la IP del gateway de la
  red `soc-lab` — obtenerla con `docker network inspect cibersecurity_project_soc-lab --format
  '{{range .IPAM.Config}}{{.Gateway}}{{end}}'` (normalmente `172.18.0.1`, pero verificarlo en cada
  entorno).
- Body:
  ```json
  { "src_ip": "<IP actual de victim-host>", "dst_ip": "$exec.data.dst_ip", "reason": "IOC C2 Conti" }
  ```
- **`src_ip` es la IP interna de Docker de `victim-host`**, no el `agent.ip` ficticio del payload
  (ese es solo ilustrativo de la empresa hipotética). Obtenerla con
  `docker inspect victim-host --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'`
  — es dinámica, cambia si se recrea el contenedor.
- Verificado end-to-end: antes del llamado, `victim-host` alcanza el destino; después, timeout —
  pero **solo hacia ese destino puntual**, el resto de la conectividad del host sigue intacta (a
  diferencia del aislamiento total de Wazuh, nodo 8).

## 7. Tarea manual — `Aprobar_Aislamiento` (User Input)

Conectado desde `AbuseIPDB_v2_1`, misma condición que LDAP. Pausa la ejecución hasta que un
analista apruebe antes de continuar hacia el aislamiento EDR (justificación: es la acción de mayor
radio de impacto, ver sección 3.2 de `ANALISIS_CONTI_Y_ARQUITECTURA.md`).

- **Name**: `Aprobar_Aislamiento`
- **Information** (Markdown):
  ```
  ## ¿Autorizar aislamiento total del host?

  **Host:** $exec.agent.name
  **Usuario comprometido:** $exec.data.srcuser (ya deshabilitado en LDAP)
  **IP de exfiltración:** $exec.data.dst_ip (ya bloqueada puntualmente en firewall)

  **VirusTotal:** $virustotal_v3_1.body.data.attributes.last_analysis_stats.malicious motores detectaron el hash como malicioso
  **AbuseIPDB:** score de abuso = $abuseipdb_v2_1.body.data.abuseConfidenceScore/100

  Esta acción corta TODO el tráfico de red del host (no solo hacia la IP de exfiltración) hasta que se revierta manualmente.
  ```
- **Input options**: no hace falta configurar Email/SMS — el warning "No Notification Type
  specified" se puede ignorar, el nodo funciona igual (probado: devuelve `SUCCESS` sin canal
  externo configurado). La aprobación se responde directamente en la vista de esa ejecución
  específica dentro de Shuffle (ver `ui_walkthrough.md`, sección de aprobación), no en un buzón
  aparte.
- **Required Input-Questions**: se define a nivel de **todo el workflow**, no dentro del nodo — en
  la configuración general del workflow ("Form Control" → "Input fields"), agregar un campo con
  sintaxis `aprobacion;Si;No` (dropdown con esas dos opciones). Recién ahí aparece seleccionable
  dentro de "Required Input-Questions" del nodo User Input.
- Verificado end-to-end: la ejecución queda en estado `WAITING` hasta la aprobación; al aprobarla
  (vía el link `frontend_continue`/`api_continue` que devuelve el propio nodo), la ejecución
  resume y termina en `FINISHED`.

## 8 y 9. Wazuh — autenticar (`wazuh`) y aislar (`wazuh_2`)

Conectados secuencialmente después de `Aprobar_Aislamiento`, solo se ejecutan si el analista
aprueba.

**8. `wazuh` — obtener token**
- Method: `POST`
- URL: `https://wazuh-manager:55000/security/user/authenticate` — se resuelve por nombre de
  contenedor sin problema.
- Username: `wazuh` / Password: `wazuh` (credenciales de fábrica del laboratorio).
- Verify: `False` (certificado autofirmado).

**9. `wazuh_2` — disparar el aislamiento**
- Method: `PUT`
- URL: `https://wazuh-manager:55000/active-response?agents_list=001` (verificar el id real del
  agente `victim-host` con `GET /agents?select=id,name` si no es `001`).
- Header: `Authorization: Bearer $wazuh.body.data.token` — **el label tiene que coincidir
  exactamente con el nombre real del nodo 8** (revisar el nombre tal cual aparece en el canvas;
  un solo carácter distinto produce `401 Invalid token` con el HTTP en verde igual, porque Shuffle
  no distingue "la llamada HTTP funcionó" de "la aplicación de destino aceptó los datos").
- Verify: `False`
- Body: `{ "command": "isolate-host0", "arguments": ["-"] }`
- **El nombre del comando lleva el sufijo `0`**: `isolate-host0`, no `isolate-host` — ver la nota
  en `infraestructura-soc/wazuh-manager/README.md`.
- Verificado end-to-end: después de este llamado, `victim-host` no alcanza absolutamente ningún
  destino (ni siquiera contenedores benignos no relacionados con el incidente, como `c2-target`),
  a diferencia del bloqueo puntual del nodo 6 — y el agente sigue apareciendo `active` en
  `GET /agents`, prueba de que no se perdió la gestión pese al aislamiento.

## Nota de networking (confirmada con pruebas reales)

Los contenedores de trabajo que Orborus crea para ejecutar cada nodo **comparten el namespace de
red del propio contenedor `shuffle-orborus`** (no crean una interfaz propia). Como `orborus` está
conectado a la red `soc-lab` (además de su red propia `shuffle`, definido en
`infraestructura-soc/shuffle/vendor/docker-compose.yml`), los nodos HTTP **sí resuelven por nombre
de contenedor** a cualquier servicio de `soc-lab` (`ldap-wrapper`, `wazuh-manager`) — confirmado
con `docker exec shuffle-orborus wget ...`. La única excepción es `firewall`, que corre en
`network_mode: host` y por eso necesita la IP del gateway (`172.18.0.1`) en vez de un nombre.

**No hace falta ninguna variable `SHUFFLE_SWARM_NETWORK_NAME`** — se probó y rompía todo el
sistema de ejecución (Orborus intentaba crear la red en modo Swarm, que este host no tiene
habilitado). El único cambio necesario en `vendor/docker-compose.yml` es agregar `soc-lab` a la
lista de `networks:` de `backend` y `orborus`, sin tocar nada relacionado a Swarm — ver
`infraestructura-soc/shuffle/README.md`.
