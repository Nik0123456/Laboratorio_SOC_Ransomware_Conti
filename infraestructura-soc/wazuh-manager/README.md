# Componente: wazuh-manager

Wazuh **solo como actuador de Active Response** (aislamiento de host) — no se usa nada de su
capa de detección/correlación, a propósito (fuera del alcance del proyecto). Shuffle llama
directamente a la API del manager, igual que llama a la API del contenedor `firewall`.

- Imagen: `wazuh/wazuh-manager:4.9.2` **sin** indexer ni dashboard (no se necesitan: no vamos a
  almacenar ni visualizar alertas). Ver `Dockerfile` — solo parchea `ossec.conf` en build time para
  habilitar dos Active Response invocables on-demand.
- API en `https://localhost:55000` — credenciales por defecto `wazuh` / `wazuh` (de fábrica, válidas
  solo para este laboratorio).
- El agente vive en el nodo `victim-host` (ver `nodos-organizacion/victim-host/entrypoint.sh`), no aquí. Este es un punto clave de la arquitectura: **el manager es centralizado, uno solo para todo el entorno** — no va "por servidor". Si se agregaran más servidores de la empresa al laboratorio, cada uno tendría su propio agente, pero seguiría habiendo un único `wazuh-manager`, igual que un SIEM.

## Active Response habilitadas

| Comando (API) | Script | Efecto |
|---|---|---|
| `firewall-drop0` | binario por defecto de Wazuh | Bloquea una IP puntual localmente en el agente (equivalente, a nivel de agente, a lo que hace el contenedor `firewall` a nivel de red) |
| `isolate-host0` | `active-response/isolate-host.sh` (propio) | Cuarentena total: bloquea TODO el tráfico del agente salvo hacia/desde el propio manager y loopback |

`isolate-host.sh` vive en este folder pero se **despliega en el agente** (`victim-host`) vía un
bind mount + copia con permisos correctos en su entrypoint — Wazuh exige que los scripts de AR estén
en `/var/ossec/active-response/bin/` del agente, no del manager.

## Por qué el nombre del comando lleva un "0" al final

Wazuh registra los comandos invocables on-demand en `/var/ossec/etc/shared/ar.conf` con el patrón
`<nombre-command>0 - <ejecutable> - 0`, generado automáticamente a partir de los bloques
`<active-response>` de `ossec.conf`. La API valida el nombre contra ese archivo, **no** contra el
`<name>` del `<command>` — por eso hay que invocar `isolate-host0`, no `isolate-host` a secas (esto
costó bastante depurar durante el desarrollo).

## Probar manualmente

```bash
# Token de la API
TOKEN=$(curl -sk -u wazuh:wazuh -X POST "https://localhost:55000/security/user/authenticate" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['token'])")

# ID del agente victim-host
curl -sk -H "Authorization: Bearer $TOKEN" "https://localhost:55000/agents?select=id,name,status"

# Disparar el aislamiento (reemplazar 001 por el id real si difiere)
curl -sk -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -X PUT "https://localhost:55000/active-response?agents_list=001" \
  -d '{"command":"isolate-host0","arguments":["-"]}'

# Verificar que quedó aislado (debe fallar TODO, no solo un destino puntual)
docker exec victim-host curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 http://c2-target/
docker exec victim-host curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 http://phpldapadmin/

# Revertir (la API no tiene un endpoint estándar de "delete" para AR custom;
# se invoca el script directamente, tal como lo haría wazuh-execd)
docker exec victim-host sh -c 'echo "{\"command\":\"delete\"}" | /var/ossec/active-response/bin/isolate-host.sh'
```

## ⚠️ Troubleshooting

**El agente se registra con un nombre aleatorio (hash del contenedor) en vez de "victim-host":**
pasa si `wazuh-manager` tarda en levantar su servicio de enrolamiento (`authd`, puerto 1515) y
`victim-host` arranca primero — el propio `wazuh-agentd` tiene un mecanismo de auto-enrolamiento
interno que puede ganarle la carrera a nuestro `agent-auth` explícito. El entrypoint de
`victim-host` ya reintenta el registro hasta 30 veces (60s) antes de rendirse; si aun así ocurre,
recrear ambos contenedores juntos: `docker compose up -d --force-recreate wazuh-manager victim-host`.

**Recrear `victim-host` solo (sin recrear `wazuh-manager`) dejando un agente "disconnected"
duplicado:** el manager conserva el registro anterior con el mismo nombre; el nuevo intento de
registro puede terminar con un nombre distinto. Para un reset limpio, recrear ambos contenedores
juntos, o borrar el agente viejo vía `DELETE /agents` antes de re-registrar.

**El error 1652 "The command used is not defined in the configuration":** ver la nota de arriba
sobre el sufijo `0` — hay que usar `isolate-host0`/`firewall-drop0`, no el nombre del `<command>`
tal cual.
