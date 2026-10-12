# Sub-componente del nodo LDAP: wrapper/

Traduce la acción de contención "deshabilitar cuenta" a una llamada HTTP simple, porque Shuffle
solo puede invocar HTTP/APIs — no puede correr `ldapmodify` por CLI dentro de un contenedor. Es lo
mismo que hace `nodos-organizacion/firewall-perimetral/app.py` pero para LDAP. Corre como
contenedor propio, pero conceptualmente es parte del mismo nodo LDAP (es la API que ese servidor
expondría para automatización, no un servicio separado).

- `POST /disable-user {"uid", "reason"}` — hace un bind real contra `openldap` (usando `ldap3`) e
  invalida el `userPassword` del usuario indicado. Acción de contención real invocada por el
  playbook de Shuffle.
- `GET /actions/log` — evidencia con timestamp de cada acción, para el informe.

Verificado end-to-end durante el desarrollo: antes de la llamada, `ssh testuser@victim-host`
autentica con éxito; después, falla (`Permission denied`, exit code 5).

```bash
curl -s -X POST http://localhost:8001/disable-user \
  -H 'Content-Type: application/json' \
  -d '{"uid": "testuser", "reason": "Conti ransomware - cuenta comprometida"}'
```
