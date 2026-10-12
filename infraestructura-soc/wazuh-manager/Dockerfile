FROM wazuh/wazuh-manager:4.9.2

# Habilita firewall-drop e isolate-host como Active Response invocables
# on-demand vía la API del manager (PUT /active-response). No se toca nada
# de la capa de detección/correlación — este proyecto no la usa.
COPY patch-ossec-conf.py /tmp/patch-ossec-conf.py
RUN python3 /tmp/patch-ossec-conf.py && rm /tmp/patch-ossec-conf.py
