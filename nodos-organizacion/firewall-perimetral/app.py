import json
import subprocess
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="SOC-Lab Firewall API")

LOG_PATH = Path("/data/actions.log")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# DOCKER-USER es la cadena que Docker reserva específicamente para que el
# usuario inserte reglas de filtrado sin que el propio Docker las sobrescriba
# al reconciliar sus reglas NAT/forwarding. El contenedor corre con
# network_mode: host + cap NET_ADMIN para poder tocar esta cadena real.
CHAIN = "DOCKER-USER"


class BlockRequest(BaseModel):
    src_ip: str
    dst_ip: str
    reason: Optional[str] = None


def log_action(action: str, **fields) -> dict:
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action,
        **fields,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def run_iptables(*args: str) -> str:
    result = subprocess.run(["iptables", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"iptables error: {result.stderr.strip()}")
    return result.stdout


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/block")
def block(req: BlockRequest):
    """Acción de contención real invocada por el playbook de Shuffle:
    inserta un DROP dirigido entre el host comprometido y el IOC (C2)."""
    run_iptables("-I", CHAIN, "-s", req.src_ip, "-d", req.dst_ip, "-j", "DROP")
    entry = log_action("block", src_ip=req.src_ip, dst_ip=req.dst_ip, reason=req.reason)
    return {"status": "blocked", "rule": entry}


@app.post("/unblock")
def unblock(req: BlockRequest):
    """Revierte un bloqueo — útil para resetear el laboratorio entre demos."""
    run_iptables("-D", CHAIN, "-s", req.src_ip, "-d", req.dst_ip, "-j", "DROP")
    entry = log_action("unblock", src_ip=req.src_ip, dst_ip=req.dst_ip, reason=req.reason)
    return {"status": "unblocked", "rule": entry}


@app.get("/rules")
def rules():
    output = run_iptables("-L", CHAIN, "-n", "--line-numbers")
    return {"chain": CHAIN, "raw": output}


@app.get("/actions/log")
def actions_log():
    """Evidencia reproducible (con timestamp) de cada acción de contención
    ejecutada — usar para la sección 'Evidencia/Comentarios' de la Plantilla
    de Respuesta y para el informe post-incidente."""
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]
