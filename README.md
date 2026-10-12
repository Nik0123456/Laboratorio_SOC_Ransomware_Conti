# Laboratorio SOC — Contención SOAR contra Ransomware Conti (Linux)

Implementación de la arquitectura contenerizada descrita en `ANALISIS_CONTI_Y_ARQUITECTURA.md`: un laboratorio de
**hosts aislados en Docker** que emula la respuesta a incidente (no la detección) ante el ataque de
ransomware Conti, con acciones de contención **reales y verificables** (no mocks que solo escriben
un log) sobre LDAP, firewall y EDR.

Todo lo descrito acá fue construido y probado end-to-end durante el desarrollo de este proyecto —
no es solo un diseño en papel. El playbook de Shuffle está completo y validado con una ejecución
real (`FINISHED`, 8/8 nodos `SUCCESS`, efecto confirmado en LDAP/firewall/Wazuh). Ver
**`ANALISIS_CONTI_Y_ARQUITECTURA.md`** para el análisis del ataque de Conti, las decisiones de
diseño y los marcos de referencia usados.

## Estructura: carpetas por nodo, agrupadas por capa arquitectónica

La organización del repo distingue tres capas, porque no todos los contenedores representan lo
mismo a nivel de arquitectura real:

```
nodos-organizacion/     ← activos reales de la empresa hipotética (lo que atacarían/protegerían)
  ldap-server/             1 nodo: openldap + phpldapadmin + wrapper/ (API HTTP del propio servidor)
  victim-host/             1 nodo: server con sshd/sssd + AGENTE Wazuh (no el manager)
  firewall-perimetral/     1 nodo: API + iptables

infraestructura-soc/    ← seguridad centralizada — NO son "por servidor", son un único nodo
                            para todo el entorno (igual que un SIEM real)
  wazuh-manager/           1 nodo: EDR manager centralizado. El agente vive en victim-host, no acá.
  shuffle/                 1 nodo: SOAR, vendorizado + incluido en el compose raíz (ver abajo)
  alert-injector/          NO es un nodo — script que sustituye al SIEM (fuera de alcance real)

lab-props/               ← no existen en la organización real, solo sirven para la demo
  c2-target/               destino de red de prueba, nada más
```

**Por qué `victim-host` y `wazuh-manager` son nodos distintos y no uno solo:** Wazuh, como todo
EDR/XDR real, es agente-manager. El **agente** es liviano y va instalado *dentro de cada servidor
protegido* (por eso vive en `victim-host`, junto al `sshd`). El **manager** es la consola
centralizada que gestiona *todos* los agentes de la organización — un único nodo para todo el
entorno, no uno por servidor. Si se agregaran más servidores al laboratorio (file server, WMS DB,
etc., como en la propuesta original), cada uno tendría su propio agente, pero seguiría existiendo
un solo `wazuh-manager`. Es exactamente la misma lógica por la que Shuffle (SOAR) también es un
nodo único y centralizado.

## Cómo levantar TODO (incluye Shuffle)

```bash
cp .env.example .env      # ajustar si se desea
docker compose up -d --build
```

Un solo comando levanta los nodos de la organización, `wazuh-manager`, y Shuffle self-hosted
completo (`shuffle-frontend`, `shuffle-backend`, `shuffle-orborus`, `shuffle-opensearch` — clon
oficial vendorizado en `infraestructura-soc/shuffle/vendor/`, incluido vía `include:` en el
`docker-compose.yml` raíz). Requiere ~4-5 GB de RAM libres, sobre todo por OpenSearch.

El agente de `victim-host` tarda ~20-40s en registrarse contra `wazuh-manager` la primera vez —
esperar antes de probar el aislamiento EDR. Shuffle tarda ~2-3 min en levantar del todo.

## Demo rápida (sin Shuffle, llamando los endpoints directo)

```bash
IP_VICTIM=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' victim-host)
IP_C2=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' c2-target)

# Baseline: todo funciona
docker run --rm --network cibersecurity_project_soc-lab alpine sh -c \
  "apk add --no-cache openssh-client sshpass >/dev/null; sshpass -p testpass123 ssh -o StrictHostKeyChecking=no testuser@victim-host echo OK"
docker exec victim-host curl -s -o /dev/null -w '%{http_code}\n' http://c2-target/

# Las 3 acciones de contención (esto es lo que haría el playbook de Shuffle)
curl -s -X POST http://localhost:8001/disable-user -d '{"uid":"testuser","reason":"demo"}' -H 'Content-Type: application/json'
curl -s -X POST http://localhost:8000/block -d "{\"src_ip\":\"$IP_VICTIM\",\"dst_ip\":\"$IP_C2\",\"reason\":\"demo\"}" -H 'Content-Type: application/json'
TOKEN=$(curl -sk -u wazuh:wazuh -X POST https://localhost:55000/security/user/authenticate | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
curl -sk -H "Authorization: Bearer $TOKEN" -X PUT "https://localhost:55000/active-response?agents_list=001" -d '{"command":"isolate-host0","arguments":["-"]}' -H 'Content-Type: application/json'

# Evidencia post-incidente: ambas deben fallar ahora
docker run --rm --network cibersecurity_project_soc-lab alpine sh -c \
  "apk add --no-cache openssh-client sshpass >/dev/null; sshpass -p testpass123 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 testuser@victim-host echo OK"
docker exec victim-host curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 http://c2-target/
```

## Con Shuffle (flujo completo) — implementado y validado end-to-end

El análisis completo del ataque de Conti, las decisiones de diseño (por qué el playbook dispara en
fase de Exfiltración, por qué las acciones de contención tienen distinto nivel de exigencia según
su radio de impacto, qué marcos de referencia se usaron y cuáles no) está en
**`ANALISIS_CONTI_Y_ARQUITECTURA.md`** — léanlo antes de reconstruir el playbook.

1. `docker compose up -d --build` (ya incluye Shuffle, ver arriba). Entrar a `http://localhost:3001`
   y crear el usuario admin (primer acceso).
2. Construir el workflow siguiendo `infraestructura-soc/shuffle/playbook/playbook_reference.md`
   (8 nodos, payloads exactos verificados) y `infraestructura-soc/shuffle/playbook/ui_walkthrough.md`
   (mecánica de la UI, ya confirmada con la construcción real, no especulativa).
3. Estructura final: `Webhook → VirusTotal → AbuseIPDB → Discord (siempre) → LDAP (condicional) →
   Firewall (siempre, desde VirusTotal) → User Input (condicional, aprobación humana) → Wazuh
   autenticar → Wazuh aislar`.
4. `export SHUFFLE_WEBHOOK_URL=...` y correr
   `python3 infraestructura-soc/alert-injector/send_alert.py`.
5. Aprobar el aislamiento cuando el playbook llegue al nodo `Aprobar_Aislamiento` (ver
   `ui_walkthrough.md`, sección "Cómo se aprueba en la práctica").
6. Repetir las verificaciones de evidencia de la sección anterior — validado con una ejecución real
   que terminó en `FINISHED` con los 8 nodos en `SUCCESS` y efecto confirmado en LDAP, firewall y
   Wazuh (no solo en la UI de Shuffle).

## Troubleshooting conocido (ya resuelto acá, documentado para no perder tiempo redescubriéndolo)

- **El bloqueo del firewall no tiene efecto** → falta `br_netfilter` en el kernel del host. Ver
  `nodos-organizacion/firewall-perimetral/README.md`.
- **El agente Wazuh se registra con nombre random en vez de "victim-host"** → condición de carrera
  en el arranque simultáneo. Ver `infraestructura-soc/wazuh-manager/README.md`.
- **`ldapmodify` "corre" pero no cambia nada** → falta `-i` en `docker exec`. Ver
  `nodos-organizacion/ldap-server/README.md`.
- **PAM dice "User account has expired" para un usuario LDAP válido** → no usar `pam_unix.so` en el
  stack `account` para usuarios 100% LDAP. Ver `nodos-organizacion/victim-host/pam-common-account`.
- **Todos los nodos del playbook de Shuffle se quedan colgados ("Worker dispatch timeout")** →
  el valor de fábrica `SHUFFLE_SWARM_CONFIG=run` hace que Orborus intente desplegar vía Docker
  Swarm, que este host no tiene habilitado. Ver `infraestructura-soc/shuffle/README.md`.
- **AbuseIPDB siempre responde 401 "APIv1 has been DEPRECATED"** → hay que usar la app
  **AbuseIPDB_v2** del catálogo de Shuffle, no "AbuseIPDB" (v1) a secas. Ver
  `infraestructura-soc/shuffle/playbook/playbook_reference.md`.
- **No aparece ningún nodo de "Condición"/"If-Else" funcional en Shuffle** → en esta versión la
  lógica condicional se configura haciendo clic en la conexión/flecha entre nodos, no en un nodo
  aparte. Ver `infraestructura-soc/shuffle/playbook/ui_walkthrough.md`.
- **No se encuentra dónde aprobar un nodo User Input pendiente** → no hay un "buzón" global, se
  aprueba con los links `frontend_continue`/`api_continue` que trae el propio resultado del nodo
  en la vista de Executions. Ver `infraestructura-soc/shuffle/playbook/ui_walkthrough.md`.
