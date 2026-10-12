#!/usr/bin/env python3
"""Simula al SIEM/EDR ya correlacionado: envía un payload de alerta directamente
al webhook de Shuffle. Este proyecto no implementa la capa de detección — este
script reemplaza esa capa a propósito, tal como fue acordado con el profesor
(alcance: solo SOAR/respuesta, no detección).

Antes de enviar, resuelve los "sentinels" del payload (strings tipo
"__VICTIM_HOST_IP__") contra el estado real del laboratorio en ese momento
(Docker/Wazuh) — esos campos representan infraestructura real, no datos del
ataque simulado, y las IPs/IDs de Docker no son estables entre reinicios de
docker compose.

Uso:
  python3 send_alert.py                                    # usa el payload de Conti (malicioso)
  python3 send_alert.py --payload benign_false_positive_alert.json
  python3 send_alert.py --webhook https://... --payload conti_exfiltration_alert.json
"""
import argparse
import base64
import json
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

PAYLOADS_DIR = Path(__file__).parent / "payloads"

WAZUH_API = os.environ.get("WAZUH_API", "https://localhost:55000")
WAZUH_USER = os.environ.get("WAZUH_USER", "wazuh")
WAZUH_PASSWORD = os.environ.get("WAZUH_PASSWORD", "wazuh")


def docker_ip(container: str) -> str:
    """IP real, en este momento, del contenedor dado — las IPs de Docker no
    son estables entre reinicios de docker compose, así que no se pueden
    hardcodear en el payload."""
    result = subprocess.run(
        ["docker", "inspect", "-f",
         "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"no se pudo obtener la IP de '{container}' (¿está corriendo?)")
    return result.stdout.strip()


def wazuh_agent_id(agent_name: str) -> str:
    """ID real del agente Wazuh registrado con ese nombre — tampoco es estable
    si el agente se llega a re-registrar desde cero."""
    ctx = ssl._create_unverified_context()
    auth = base64.b64encode(f"{WAZUH_USER}:{WAZUH_PASSWORD}".encode()).decode()
    token_req = urllib.request.Request(
        f"{WAZUH_API}/security/user/authenticate", method="POST",
        headers={"Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(token_req, context=ctx, timeout=5) as resp:
        token = json.load(resp)["data"]["token"]

    agents_req = urllib.request.Request(
        f"{WAZUH_API}/agents?select=id,name",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(agents_req, context=ctx, timeout=5) as resp:
        agents = json.load(resp)["data"]["affected_items"]

    for agent in agents:
        if agent["name"] == agent_name:
            return agent["id"]
    raise RuntimeError(f"no hay ningún agente Wazuh registrado como '{agent_name}'")


# Placeholders que puede traer un payload para los campos que representan
# estado real del laboratorio (no datos del ataque simulado, esos se quedan
# hardcodeados en el JSON).
SENTINELS = {
    "__VICTIM_HOST_IP__": lambda: docker_ip("victim-host"),
    "__C2_TARGET_IP__": lambda: docker_ip("c2-target"),
    "__VICTIM_HOST_AGENT_ID__": lambda: wazuh_agent_id("victim-host"),
}


def resolve_sentinels(value):
    if isinstance(value, dict):
        return {k: resolve_sentinels(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_sentinels(v) for v in value]
    if isinstance(value, str) and value in SENTINELS:
        return SENTINELS[value]()
    return value


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--payload",
        default="conti_exfiltration_alert.json",
        help="Nombre de archivo dentro de payloads/ (default: conti_exfiltration_alert.json)",
    )
    parser.add_argument(
        "--webhook",
        default=os.environ.get("SHUFFLE_WEBHOOK_URL"),
        help="URL del webhook de Shuffle (default: variable de entorno SHUFFLE_WEBHOOK_URL)",
    )
    args = parser.parse_args()

    if not args.webhook:
        print(
            "ERROR: falta la URL del webhook. Pasar --webhook o exportar "
            "SHUFFLE_WEBHOOK_URL (ver shuffle/README.md para obtenerla).",
            file=sys.stderr,
        )
        sys.exit(1)

    payload_path = PAYLOADS_DIR / args.payload
    if not payload_path.exists():
        print(f"ERROR: no existe {payload_path}", file=sys.stderr)
        sys.exit(1)

    payload = json.loads(payload_path.read_text())
    try:
        payload = resolve_sentinels(payload)
    except RuntimeError as e:
        print(f"ERROR resolviendo estado real del laboratorio: {e}", file=sys.stderr)
        sys.exit(1)

    body = json.dumps(payload).encode()

    req = urllib.request.Request(
        args.webhook,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"Enviando {payload_path.name} -> {args.webhook}")
    print(
        f"  agent.ip={payload.get('agent', {}).get('ip')}  "
        f"agent.id={payload.get('agent', {}).get('id')}  "
        f"data.dst_ip={payload.get('data', {}).get('dst_ip')}"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"HTTP {resp.status}")
            print(resp.read().decode(errors="replace"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"No se pudo conectar al webhook: {e.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
