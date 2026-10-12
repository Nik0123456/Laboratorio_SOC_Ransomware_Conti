# Componente: firewall

API REST mínima (FastAPI) que aplica bloqueo de red **real** entre contenedores insertando reglas
en la cadena `DOCKER-USER` del netfilter del host — la cadena que Docker reserva para reglas de
usuario sin que el propio daemon las sobrescriba.

- `POST /block {"src_ip", "dst_ip", "reason"}` — acción de contención real invocada por el
  playbook de Shuffle.
- `POST /unblock {"src_ip", "dst_ip"}` — revierte el bloqueo (para resetear la demo).
- `GET /rules` — muestra la cadena `DOCKER-USER` tal como está en el host.
- `GET /actions/log` — historial con timestamp de cada acción — usarlo como evidencia en el
  informe.

Corre con `network_mode: host` + `cap_add: NET_ADMIN`: necesita estar en el namespace de red del
host porque el tráfico entre contenedores de la red `soc-lab` pasa por el netfilter **del host**,
no por uno propio del contenedor. Por eso no lleva `networks:` en el compose — al usar `host`, el
puerto 8000 queda expuesto directamente en `localhost:8000` del host, sin necesidad de `ports:`.

## Cómo obtener las IPs para probar

```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' victim-host
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' c2-target
```

## Prueba manual (antes/después)

```bash
# Antes: debe responder 200
docker exec victim-host curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 http://c2-target/

curl -s -X POST http://localhost:8000/block \
  -H 'Content-Type: application/json' \
  -d '{"src_ip": "<ip victim-host>", "dst_ip": "<ip c2-target>", "reason": "IOC C2 Conti"}'

# Después: debe fallar (000 / timeout)
docker exec victim-host curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 http://c2-target/
```

## ⚠️ Troubleshooting importante: el bloqueo no tiene efecto (curl sigue devolviendo 200)

Esto le va a pasar en máquinas donde el kernel no tiene cargado el módulo `br_netfilter`, que es
lo que hace que el tráfico **entre contenedores del mismo bridge de Docker** efectivamente pase
por netfilter/iptables del host (sin él, Docker reenvía el tráfico a nivel de puente L2 sin pasar
por ninguna cadena de `iptables`, así que aunque la regla se inserte, nunca se evalúa). Se
diagnosticó exactamente este problema durante el desarrollo de este componente.

Diagnóstico:
```bash
cat /proc/sys/net/bridge/bridge-nf-call-iptables
# Si el archivo no existe → br_netfilter no está cargado.
```

Solución (requiere acceso al host, no basta con estar dentro de un contenedor):
```bash
sudo modprobe br_netfilter
echo 1 | sudo tee /proc/sys/net/bridge/bridge-nf-call-iptables
```

Si van a correr esto en una VM/laptop propia (no en un entorno ya sandboxeado), casi seguro alcanza
con el `modprobe` normal como root. Si están dentro de un entorno ya containerizado/anidado (poco
probable para el proyecto, pero por si acaso), se necesita un contenedor `--privileged --pid=host`
que entre al namespace del host vía `nsenter` para cargar el módulo — ver el historial de este
proyecto si hace falta ese caso extremo.
