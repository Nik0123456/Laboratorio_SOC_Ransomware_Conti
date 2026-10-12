#!/bin/bash
set -e

# Permisos que SSSD exige o se niega a arrancar.
chown root:root /etc/sssd/sssd.conf
chmod 600 /etc/sssd/sssd.conf

mkdir -p /var/run/sshd

# ssh-keygen -A no regenera si ya existen (idempotente entre reinicios de contenedor).
ssh-keygen -A >/dev/null 2>&1 || true

echo "[entrypoint] arrancando sssd..."
sssd -D

# Espera activa a que sssd realmente resuelva al usuario LDAP antes de aceptar
# logins (evita falsos negativos de "usuario no existe" justo tras el arranque).
for i in $(seq 1 15); do
  if getent passwd testuser >/dev/null 2>&1; then
    echo "[entrypoint] sssd resuelve testuser correctamente."
    break
  fi
  sleep 1
done

echo "[entrypoint] arrancando sshd..."
/usr/sbin/sshd

# ── Agente Wazuh: solo como actuador de Active Response ────────────
# Despliega el script custom de aislamiento (llega montado desde
# wazuh-manager/active-response/ vía docker-compose) con los permisos que
# wazuh-execd exige (root:wazuh, no escribible por grupo/otros).
if [ -f /opt/wazuh-ar/isolate-host.sh ] && [ -d /var/ossec/active-response/bin ]; then
  cp /opt/wazuh-ar/isolate-host.sh /var/ossec/active-response/bin/isolate-host.sh
  chown root:wazuh /var/ossec/active-response/bin/isolate-host.sh
  chmod 750 /var/ossec/active-response/bin/isolate-host.sh
  echo "[entrypoint] isolate-host.sh desplegado en active-response/bin."
fi

if [ -d /var/ossec ]; then
  echo "[entrypoint] esperando a que wazuh-manager esté disponible..."
  for i in $(seq 1 30); do
    if getent hosts wazuh-manager >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  # Reintentar el registro hasta que authd del manager acepte conexiones.
  # Un solo intento falla casi siempre en un "docker compose up" desde cero:
  # wazuh-manager tarda más en levantar authd (puerto 1515) que en resolver
  # por DNS, y wazuh-agentd tiene su propio mecanismo interno de
  # auto-enrolamiento que puede ganarle la carrera a este script y registrar
  # el agente con un nombre aleatorio en vez de "victim-host" si no
  # reintentamos aquí primero.
  if [ ! -s /var/ossec/etc/client.keys ]; then
    echo "[entrypoint] registrando agente contra wazuh-manager (con reintentos)..."
    for i in $(seq 1 30); do
      if /var/ossec/bin/agent-auth -m wazuh-manager -A victim-host; then
        echo "[entrypoint] agente registrado como 'victim-host'."
        break
      fi
      sleep 2
    done
  fi
  sed -i 's/<address>MANAGER_IP<\/address>/<address>wazuh-manager<\/address>/' /var/ossec/etc/ossec.conf

  echo "[entrypoint] arrancando agente Wazuh..."
  /var/ossec/bin/wazuh-control start || true
fi

echo "[entrypoint] sshd y agente arriba, manteniendo el contenedor vivo..."
exec tail -f /var/ossec/logs/ossec.log 2>/dev/null || exec sleep infinity
