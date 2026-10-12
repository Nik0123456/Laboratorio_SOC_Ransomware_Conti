# Nodo: Shuffle (SOAR)

Infraestructura del SOC, **un solo nodo centralizado** para todo el entorno (no es "por servidor",
igual que `wazuh-manager`). Es el clon oficial de [Shuffle/Shuffle](https://github.com/Shuffle/Shuffle)
vendorizado en `vendor/` e incluido directamente en el `docker-compose.yml` raíz vía la directiva
`include:`, para poder levantar todo con un solo `docker compose up -d`.

## Por qué está vendorizado (copiado) en vez de referenciado

`include:` de Docker Compose necesita el archivo `docker-compose.yml` disponible localmente — no
hay forma de apuntarlo a una URL remota. Por eso `vendor/` es una copia real del repo oficial (sin
`.git`, para no duplicar historial dentro de este proyecto).

**Cambios respecto al original** (para poder integrarlo con el resto del laboratorio y hacerlo
funcionar en un host sin Docker Swarm):

1. `vendor/docker-compose.yml` — se agregó `soc-lab` a la lista de redes de `backend` y `orborus`
   (además de su red propia `shuffle`). Esto alcanza para que los nodos del playbook resuelvan
   `ldap-wrapper` y `wazuh-manager` por nombre de contenedor — confirmado con pruebas reales (ver
   la nota de networking más abajo, es un poco no-obvio *por qué* alcanza con esto).
2. `vendor/docker-compose.yml`, servicio `orborus` — se cambió `SHUFFLE_SWARM_CONFIG=run` (valor de
   fábrica) por **vacío**. Revisando el código fuente (`functions/onprem/worker/worker.go`), los
   valores `"run"` y `"swarm"` toman exactamente el mismo camino: Orborus despliega los workers
   como servicios de **Docker Swarm**, e incluso intenta auto-inicializar el swarm si no existe.
   En un host sin Swarm (o donde el auto-init falla por ambigüedad de IP de red, como en el entorno
   donde se desarrolló este proyecto) esto deja a **todos** los nodos del playbook colgados
   indefinidamente ("Worker dispatch timeout"), no solo los propios — es un problema de
   infraestructura, no del workflow. Con el valor vacío, Orborus despliega los workers como
   contenedores Docker normales, sin Swarm.

Se probó explícitamente agregar `SHUFFLE_SWARM_NETWORK_NAME=soc-lab` a `vendor/.env` pensando que
haría que los workers se unan a `soc-lab` — **se revirtió**, porque con un nombre de red custom
Orborus intenta crearla en modo Swarm y rompe todo el sistema de ejecución. No hace falta esa
variable — ver la nota de networking.

Si en algún momento vuelven a clonar Shuffle desde cero, hay que reaplicar estos dos cambios.

## Por qué self-hosted y no Shuffle Cloud

En un despliegue real, un SOC casi siempre auto-hospeda su SOAR (maneja credenciales de sistemas
internos, no quiere mandar datos de incidentes a un tercero). Al haber sacado Wazuh del stack de
detección (no se usa para eso, solo como actuador puntual), sobra presupuesto de RAM para
auto-hospedar también Shuffle sin problema.

**Validado durante el desarrollo de este proyecto:** el stack completo (`frontend`, `backend`,
`orborus`, `opensearch`) levanta limpio, sin tocar nada más allá de los dos cambios de arriba, en
unos 2-3 minutos.

## Despliegue

Ya queda incluido al correr, desde la raíz del proyecto:

```bash
docker compose up -d --build
```

Requiere ~3-4 GB de RAM libres adicionales (el grueso es OpenSearch, que por defecto reserva 3GB de
heap — ajustable en `vendor/docker-compose.yml` vía `OPENSEARCH_JAVA_OPTS` si la máquina es más
chica). Contenedores: `shuffle-frontend`, `shuffle-backend`, `shuffle-orborus`,
`shuffle-opensearch`.

**Nota:** Orborus crea por su cuenta, al arrancar, un contenedor `tenzir-node` y una red
`tenzir-network` (no configurados por nosotros — es comportamiento de fábrica de Shuffle, aparenta
ser una integración de datos que trae por defecto). No interfieren con el laboratorio; `docker
compose down` no los limpia porque no son parte de este proyecto de compose — hay que sacarlos a
mano si se quiere un reset completo: `docker rm -f tenzir-node && docker network rm tenzir-network`.

Primer acceso: `http://localhost:3001` — la primera vez pide crear el usuario/organización admin
(no hay usuario por defecto, el `.env` de fábrica lo deja vacío a propósito).

## Crear el workflow y obtener la URL del webhook

1. Crear un Workflow nuevo (vacío).
2. Agregar un nodo **Webhook** como Startpoint/Trigger.
3. Shuffle muestra la URL del webhook directamente en el nodo — tiene la forma
   `http://localhost:5001/api/v1/hooks/<hook-id>`. Esa es la URL que va en
   `SHUFFLE_WEBHOOK_URL` (ver `infraestructura-soc/alert-injector/README.md`).
4. El resto de nodos del playbook se detallan en `playbook/playbook_reference.md`.

## Cómo direccionar los nodos HTTP del playbook hacia los otros nodos del laboratorio

**Confirmado con pruebas reales** (no es teoría): los contenedores que Orborus crea para ejecutar
cada nodo del playbook **comparten el namespace de red del propio contenedor `shuffle-orborus`**
(no tienen interfaz de red propia — `docker inspect` de cualquiera de esos contenedores muestra
`NetworkMode: container:<id-de-orborus>`). Como `orborus` está en la red `soc-lab` (por el cambio
de la sección anterior), **cualquier nodo del playbook resuelve por nombre de contenedor** a los
servicios de esa red:

- `http://ldap-wrapper:8001/...` — funciona directo.
- `https://wazuh-manager:55000/...` — funciona directo.

**Única excepción: `firewall`**, que corre en `network_mode: host` y por lo tanto no tiene nombre
resoluble en ninguna red Docker. Para ese nodo específico, usar la IP del gateway de `soc-lab` en
vez de un nombre — **`host.docker.internal` no resuelve en este entorno Linux** (probado, falla
con "bad address"). Obtener el gateway real con:

```bash
docker network inspect cibersecurity_project_soc-lab --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

Normalmente `172.18.0.1`, pero conviene verificarlo en cada entorno — no es necesariamente estable
entre distintas máquinas o después de un `docker compose down -v`.

## Apps que hacen falta agregar a las credenciales de Shuffle

- **VirusTotal_v3** — app ya incluida en el catálogo de Shuffle. Pide una API key (free tier en
  virustotal.com). Acción usada: `get_a_hash_report_`.
- **AbuseIPDB_v2** — usar específicamente la variante **v2** del catálogo, no "AbuseIPDB" a secas.
  La acción vieja (v1, `get_check_ip`) llama a un endpoint dado de baja por AbuseIPDB y siempre
  devuelve 401 "APIv1 has been DEPRECATED" — confirmado con pruebas reales, no es un problema de
  configuración. Pide API key (free tier en abuseipdb.com).
- Para los nodos hacia `firewall`, `ldap-wrapper`, `wazuh-manager` y la notificación de Discord no
  hace falta ninguna app especial — alcanza con el nodo genérico **HTTP** (method + URL + headers +
  body), que ya viene incluido por defecto.
- Detalle completo de cada nodo del playbook, incluyendo el diseño de respuesta graduada (LDAP y
  aislamiento EDR condicionados al enriquecimiento, firewall siempre activo, aprobación humana
  antes del aislamiento): `playbook/playbook_reference.md` y `ANALISIS_CONTI_Y_ARQUITECTURA.md`
  (raíz del proyecto).
