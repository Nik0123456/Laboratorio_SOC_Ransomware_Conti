import json
import os
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from ldap3 import Connection, Server, MODIFY_REPLACE
from pydantic import BaseModel

app = FastAPI(title="SOC-Lab LDAP Containment API")

LDAP_URI = os.environ.get("LDAP_URI", "ldap://openldap:389")
LDAP_ADMIN_DN = os.environ.get("LDAP_ADMIN_DN", "cn=admin,dc=empresa,dc=local")
LDAP_ADMIN_PASSWORD = os.environ.get("LDAP_ADMIN_PASSWORD", "changeme")
LDAP_PEOPLE_OU = os.environ.get("LDAP_PEOPLE_OU", "ou=people,dc=empresa,dc=local")

LOG_PATH = Path("/data/actions.log")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


class DisableUserRequest(BaseModel):
    uid: str
    reason: str | None = None


def log_action(action: str, **fields) -> dict:
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action,
        **fields,
    }
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/disable-user")
def disable_user(req: DisableUserRequest):
    """Acción de contención real invocada por el playbook de Shuffle: invalida
    la contraseña LDAP del usuario comprometido (equivalente a deshabilitar la
    cuenta) contra el directorio real openldap."""
    dn = f"uid={req.uid},{LDAP_PEOPLE_OU}"
    new_value = f"BLOQUEADA-POR-INCIDENTE-{secrets.token_hex(8)}"

    server = Server(LDAP_URI)
    conn = Connection(server, user=LDAP_ADMIN_DN, password=LDAP_ADMIN_PASSWORD, auto_bind=True)
    try:
        ok = conn.modify(dn, {"userPassword": [(MODIFY_REPLACE, [new_value])]})
        if not ok:
            raise HTTPException(status_code=500, detail=f"ldap modify failed: {conn.result}")
    finally:
        conn.unbind()

    entry = log_action("ldap_disable_user", uid=req.uid, dn=dn, reason=req.reason)
    return {"status": "disabled", "rule": entry}


@app.get("/actions/log")
def actions_log():
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]
