# Guía de comandos para probar el laboratorio (reset → baseline → alerta → evidencia)

Secuencia completa de comandos para repetir una demo del playbook desde cero. Asume que
`docker compose up -d --build` ya corrió y todos los contenedores están arriba (ver `README.md`).

Variables usadas en todo el documento:

```bash
NET=cibersecurity_project_soc-lab   # nombre de la red generado por compose (prefijo = nombre de la carpeta del proyecto)
IP_VICTIM=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' victim-host)
IP_C2=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' c2-target)
```

---

## 1. Resetear el laboratorio (revertir restricciones de una corrida anterior)

Si ya corriste el playbook antes, estas 3 acciones de contención van a seguir aplicadas. Hay que
revertirlas antes de repetir la prueba, si no la "baseline" del paso 2 va a fallar.

### 1.1 LDAP — restaurar la contraseña de `testuser`

El wrapper (`ldap-wrapper`) solo expone `/disable-user`, no un `/enable-user` — deshabilitar es la
única acción de contención real que necesita el playbook. Para resetear el laboratorio, hay que
hablarle directo a `openldap` con `ldapmodify`. **Importante:** `docker exec` necesita el flag `-i`
para que el heredoc llegue por stdin — sin `-i` el comando "corre" pero no cambia nada (ver
troubleshooting en `nodos-organizacion/ldap-server/README.md`).

```bash
docker exec -i openldap ldapmodify -x -D "cn=admin,dc=empresa,dc=local" -w changeme <<'EOF'
dn: uid=testuser,ou=people,dc=empresa,dc=local
changetype: modify
replace: userPassword
userPassword: testpass123
EOF
```

### 1.2 Firewall — quitar el bloqueo de `DOCKER-USER`

Primero ver qué reglas quedaron activas:

```bash
curl -s http://localhost:8000/rules
```

Revertir la regla puntual (mismos `src_ip`/`dst_ip` con los que se bloqueó — `IP_VICTIM` → `IP_C2`,
ver variables arriba — **siempre que el nodo `firewall` del playbook ya use `$exec.agent.ip` como
`src_ip`**; si todavía tiene el valor viejo hardcodeado, mirar la salida de `/rules` para saber qué
IP se bloqueó realmente):

```bash
curl -s -X POST http://localhost:8000/unblock \
  -H 'Content-Type: application/json' \
  -d "{\"src_ip\":\"$IP_VICTIM\",\"dst_ip\":\"$IP_C2\"}"
```

Si `IP_VICTIM`/`IP_C2` cambiaron entre corridas (por ejemplo tras un `docker compose down`), mirar
la salida de `/rules` para saber las IPs exactas a pasar en el `unblock`.

### 1.3 Wazuh — revertir el aislamiento total del host

Convención de la API de Active Response de Wazuh: para deshacer una acción ya aplicada, se llama al
mismo comando con `!` antepuesto (dispara el branch `delete` de `isolate-host.sh`, no `add`).

```bash
TOKEN=$(curl -sk -u wazuh:wazuh -X POST https://localhost:55000/security/user/authenticate \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")

curl -sk -H "Authorization: Bearer $TOKEN" -X PUT \
  "https://localhost:55000/active-response?agents_list=001" \
  -H 'Content-Type: application/json' \
  -d '{"command":"!isolate-host0","arguments":["-"]}'
```

`001` es el ID del agente `victim-host` (único agente registrado). Si hay dudas, confirmar con:

```bash
curl -sk -H "Authorization: Bearer $TOKEN" https://localhost:55000/agents | python3 -m json.tool
```

---

## 2. Probar que las conexiones "buenas" funcionan (baseline, antes de la alerta)

Con las 3 restricciones ya revertidas, confirmar que todo funciona normal:

```bash
# SSH con la contraseña original — debe imprimir "OK"
docker run --rm --network "$NET" alpine sh -c \
  "apk add --no-cache openssh-client sshpass >/dev/null; \
   sshpass -p testpass123 ssh -o StrictHostKeyChecking=no testuser@victim-host echo OK"

# victim-host → c2-target — debe devolver 200
docker exec victim-host curl -s -o /dev/null -w '%{http_code}\n' http://c2-target/
```

Si cualquiera de los dos falla acá, el problema es del reset del paso 1, no del playbook — no seguir
a la alerta hasta que ambos den resultado limpio.

---

## 3. Emular la alerta del SIEM (dispara el playbook de Shuffle)

Este proyecto no implementa detección — `send_alert.py` reemplaza al SIEM enviando directo el
payload de la alerta (fase de Exfiltración) al webhook de Shuffle.

**Requisito nuevo:** antes de enviar, el script resuelve automáticamente los campos del payload que
representan estado real del laboratorio (`agent.ip`, `agent.id`, y en el payload de Conti
`data.dst_ip`) contra `docker inspect` y la API de Wazuh — por eso necesita `victim-host`,
`c2-target` y `wazuh-manager` ya arriba (y el agente Wazuh ya registrado) antes de correr este paso,
no solo el webhook de Shuffle. Si falla con `ERROR resolviendo estado real del laboratorio: ...`,
es que alguno de esos tres todavía no está listo.

```bash
export SHUFFLE_WEBHOOK_URL="http://localhost:3001/api/v1/hooks/webhook_284b83dd-dc3b-449f-942f-0f8499deec13"  # ver Shuffle README
python3 infraestructura-soc/alert-injector/send_alert.py
```

El script imprime los valores resueltos (`agent.ip`, `agent.id`, `data.dst_ip`) antes de enviar —
compararlos contra `$IP_VICTIM`/`$IP_C2` (variables del inicio de esta guía) es la forma más rápida
de confirmar que la alerta salió con las IPs correctas de esta corrida, sin tener que esperar a la
evidencia del paso 4.

El payload por defecto es `conti_exfiltration_alert.json` (malicioso, dispara LDAP + Firewall +
aprobación + aislamiento). `data.dst_ip` en este payload ahora apunta al propio `c2-target` del
laboratorio (antes era una IP externa ficticia) — por diseño, ya no se espera que AbuseIPDB aporte
nada útil (una IP privada RFC1918 no tiene reputación pública que consultar); la detección de este
playbook depende del hash en VirusTotal, no de la IP. Para probar que un falso positivo NO dispara
contención:

```bash
python3 infraestructura-soc/alert-injector/send_alert.py --payload benign_false_positive_alert.json
```

**No olvidar:** entrar a la ejecución en la vista **Executions** de Shuffle y aprobar el nodo
`Aprobar_Aislamiento` (link `frontend_continue`) antes de que pase el timeout de ~2 minutos del
worker — ver `infraestructura-soc/shuffle/playbook/ui_walkthrough.md`, sección "Cómo se aprueba en
la práctica".

---

## 4. Verificar que las acciones de contención se aplicaron (evidencia post-incidente)

```bash
# Logs de acciones reales (no solo estado en la UI de Shuffle)
curl -s http://localhost:8001/actions/log | python3 -m json.tool   # debe tener "ldap_disable_user"
curl -s http://localhost:8000/actions/log | python3 -m json.tool   # debe tener "block"

# SSH con la contraseña original — ahora debe FALLAR
docker run --rm --network "$NET" alpine sh -c \
  "apk add --no-cache openssh-client sshpass >/dev/null; \
   sshpass -p testpass123 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 testuser@victim-host echo OK"

# victim-host → c2-target — ahora debe FALLAR (timeout, por el aislamiento total de Wazuh)
docker exec victim-host curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 http://c2-target/

# El agente debe seguir "active" pese al aislamiento (prueba de que no se perdió la gestión)
curl -sk -H "Authorization: Bearer $TOKEN" https://localhost:55000/agents | python3 -m json.tool
```

Para repetir la demo, volver al paso 1.
