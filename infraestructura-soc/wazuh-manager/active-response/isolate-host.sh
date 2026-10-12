#!/bin/sh
# Active Response custom de Wazuh: cuarentena total del host.
# A diferencia del "firewall-drop" (que bloquea un único IOC puntual), este
# script corta TODO el tráfico saliente/entrante del host excepto el que va
# hacia/desde el propio Wazuh manager (para no perder la gestión del agente).
#
# Se despliega en el AGENTE (victim-host) en /var/ossec/active-response/bin/,
# no en el manager. Wazuh entrega el mensaje de la acción como JSON por stdin
# con un campo "command" que vale "add" (aplicar) o "delete" (revertir).

LOG_FILE="/var/ossec/logs/active-responses.log"
STATE_FILE="/var/ossec/active-response/bin/.isolate-host.manager_ip"
log() { echo "$(date '+%Y/%m/%d %H:%M:%S') isolate-host: $1" >> "$LOG_FILE"; }

read -r INPUT_JSON
COMMAND=$(echo "$INPUT_JSON" | grep -o '"command"[[:space:]]*:[[:space:]]*"[a-z]*"' | cut -d'"' -f4)

case "$COMMAND" in
  add)
    MANAGER_IP=$(getent hosts wazuh-manager | awk '{print $1}' | head -n1)
    if [ -z "$MANAGER_IP" ]; then
      log "no se pudo resolver wazuh-manager, abortando para no perder gestión del agente"
      exit 1
    fi
    # Se cachea la IP porque, una vez aislado, el propio DNS local (embedded
    # resolver de Docker en 127.0.0.11) queda cortado por el DROP de OUTPUT
    # salvo que loopback esté explícitamente exceptuado (ver reglas abajo).
    # Cachear la IP hace el "delete" resistente aunque loopback fallara.
    echo "$MANAGER_IP" > "$STATE_FILE"
    iptables -I OUTPUT -o lo -j ACCEPT
    iptables -I INPUT -i lo -j ACCEPT
    iptables -I OUTPUT ! -d "$MANAGER_IP" -j DROP
    iptables -I INPUT ! -s "$MANAGER_IP" -j DROP
    log "host aislado — solo se permite tráfico hacia/desde el manager ($MANAGER_IP) y loopback"
    ;;
  delete)
    MANAGER_IP=$(cat "$STATE_FILE" 2>/dev/null)
    [ -z "$MANAGER_IP" ] && MANAGER_IP=$(getent hosts wazuh-manager | awk '{print $1}' | head -n1)
    iptables -D OUTPUT ! -d "$MANAGER_IP" -j DROP 2>/dev/null
    iptables -D INPUT ! -s "$MANAGER_IP" -j DROP 2>/dev/null
    iptables -D OUTPUT -o lo -j ACCEPT 2>/dev/null
    iptables -D INPUT -i lo -j ACCEPT 2>/dev/null
    rm -f "$STATE_FILE"
    log "aislamiento revertido"
    ;;
  *)
    log "comando desconocido recibido: '$COMMAND'"
    ;;
esac

exit 0
