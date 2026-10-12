#!/usr/bin/env python3
"""Habilita, en tiempo de build, las dos Active Response que usa el laboratorio:
- firewall-drop (viene predefinida en la imagen, solo hace falta activarla)
- isolate-host (comando propio, cuarentena total del host salvo el manager)

Se parchea el ossec.conf de fábrica en vez de reemplazarlo entero para no
perder el resto de la configuración por defecto (reglas, decoders, etc).
"""
import sys

# OJO: NO es /var/ossec/etc/ossec.conf. Esa ruta todavía no existe en tiempo
# de build — la imagen la genera recién al arrancar el contenedor, copiándola
# desde esta plantilla "permanente". Parchear la ruta final directamente
# fallaría con FileNotFoundError durante el build.
OSSEC_CONF = "/var/ossec/data_tmp/permanent/var/ossec/etc/ossec.conf"

ANCHOR = """  <!--
  <active-response>
    active-response options here
  </active-response>
  -->"""

REPLACEMENT = """  <command>
    <name>isolate-host</name>
    <executable>isolate-host.sh</executable>
    <timeout_allowed>yes</timeout_allowed>
  </command>

  <active-response>
    <disabled>no</disabled>
    <command>firewall-drop</command>
    <location>all</location>
    <timeout>0</timeout>
  </active-response>

  <active-response>
    <disabled>no</disabled>
    <command>isolate-host</command>
    <location>all</location>
    <timeout>0</timeout>
  </active-response>"""

with open(OSSEC_CONF) as f:
    content = f.read()

if "isolate-host" in content:
    print("ossec.conf ya parchado, nada que hacer.")
    sys.exit(0)

if ANCHOR not in content:
    print("ERROR: no se encontró el bloque esperado en ossec.conf — "
          "puede que la imagen de wazuh-manager haya cambiado su plantilla "
          "por defecto. Revisar manualmente.", file=sys.stderr)
    sys.exit(1)

content = content.replace(ANCHOR, REPLACEMENT)

with open(OSSEC_CONF, "w") as f:
    f.write(content)

print("ossec.conf parchado: firewall-drop e isolate-host habilitados como Active Response.")
