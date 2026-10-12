# Componente: alert-injector

Reemplaza a propósito la capa de detección/SIEM (fuera del alcance del proyecto). Es el único
"componente" que no corre como contenedor — es un script que ustedes ejecutan manualmente (o desde
el runner de CI que prefieran) para simular que un SIEM/EDR ya correlacionó un evento y ahora
notifica al SOAR, exactamente el mismo tipo de webhook que enviaría un Wazuh/Splunk real.

## Uso

```bash
export SHUFFLE_WEBHOOK_URL="https://...la-url-que-genera-shuffle-al-crear-el-workflow..."

# Caso verdadero positivo (dispara la rama de contención completa del playbook)
python3 send_alert.py --payload conti_exfiltration_alert.json

# Caso falso positivo (para demostrar que el playbook también sabe cerrar sin contener)
python3 send_alert.py --payload benign_false_positive_alert.json
```

## Payloads incluidos

- `payloads/conti_exfiltration_alert.json` — alerta con forma de evento Wazuh/EDR, representando
  exactamente la fase de **Exfiltración** del Kill Chain (Rclone hacia almacenamiento externo) —
  el punto exacto donde el profesor indicó que debe arrancar el playbook. Incluye el mapeo MITRE
  ATT&CK T1567.002 embebido en el propio payload para que el playbook pueda loguearlo directamente
  en el caso/ticket.
- `payloads/benign_false_positive_alert.json` — mismo patrón de actividad pero con IOCs limpios
  (IP/hash que no deberían salir maliciosos en VirusTotal/AbuseIPDB), para demostrar la rama de
  "Falso Positivo" del playbook sin ejecutar ninguna acción de contención.

Ambos usan IOCs de ejemplo con fines académicos (no corresponden necesariamente a infraestructura
real activa).
