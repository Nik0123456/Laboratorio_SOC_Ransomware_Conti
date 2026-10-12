# Componente: LDAP

Directorio real (OpenLDAP) usado por `victim-host` para autenticación SSH, y objetivo real de la
acción de contención "deshabilitar cuenta" del playbook.

- Imagen: `osixia/openldap` (bien mantenida, estándar para labs).
- UI opcional: `osixia/phpldapadmin` en `http://localhost:8080` (bind DN
  `cn=admin,dc=empresa,dc=local`, password ver `.env`).
- Dominio: `dc=empresa,dc=local` — Organización: "Logistica SAC".
- Bootstrap: `bootstrap/01-people.ldif` crea `ou=people`, `ou=groups` y el usuario
  `uid=testuser,ou=people,dc=empresa,dc=local` (password inicial `testpass123`).

## Verificar que el directorio quedó poblado

```bash
docker exec openldap ldapsearch -x -H ldap://localhost \
  -b "dc=empresa,dc=local" -D "cn=admin,dc=empresa,dc=local" -w changeme \
  "(uid=testuser)"
```

## Acción de contención real (la que ejecuta el playbook de Shuffle)

**El playbook de Shuffle no llama a este contenedor directamente** — Shuffle solo puede invocar
HTTP, y `ldapmodify` es un comando CLI. La acción real que dispara el playbook es un `POST` al
wrapper HTTP en `wrapper/` (`http://ldap-wrapper:8001/disable-user`), que internamente hace el bind
LDAP y el modify. Ver `wrapper/README.md`.

Lo siguiente es el equivalente manual por CLI (útil para depurar o para entender qué hace el
wrapper por debajo), pero no es lo que invoca el playbook:

```bash
# OJO: el -i en "docker exec -i" es obligatorio para que el heredoc llegue
# por stdin al proceso dentro del contenedor. Sin -i el comando "corre" sin
# error pero no aplica ningún cambio real (nos pasó durante las pruebas).
docker exec -i openldap ldapmodify -x -H ldap://localhost \
  -D "cn=admin,dc=empresa,dc=local" -w changeme <<EOF
dn: uid=testuser,ou=people,dc=empresa,dc=local
changetype: modify
replace: userPassword
userPassword: BLOQUEADA-POR-INCIDENTE-$(date +%s)
EOF
```

Después de esto, cualquier intento de `ssh testuser@victim-host` con la contraseña original debe
fallar (`Permission denied`, exit code 5) — esa es la evidencia de contención real que se documenta
en el informe. Verificado end-to-end durante el desarrollo de este componente.
