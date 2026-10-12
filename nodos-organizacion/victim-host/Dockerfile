FROM debian:bookworm-slim

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        openssh-server \
        sssd-ldap \
        libnss-sss \
        libpam-sss \
        ldap-utils \
        curl \
        gnupg \
        ca-certificates \
        lsb-release \
        iptables \
        iproute2 \
        iputils-ping \
        netcat-openbsd \
        procps \
    && rm -rf /var/lib/apt/lists/*

# Agente Wazuh — se usa exclusivamente como actuador de Active Response
# (aislamiento de host), invocado on-demand por Shuffle vía la API del
# manager. No se configura ninguna regla de correlación ni detección.
RUN curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH \
        | gpg --no-default-keyring --keyring gnupg-ring:/usr/share/keyrings/wazuh.gpg --import \
    && chmod 644 /usr/share/keyrings/wazuh.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main" \
        > /etc/apt/sources.list.d/wazuh.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends wazuh-agent=4.9.2-1 \
    && rm -rf /var/lib/apt/lists/*

# nsswitch: hacer que passwd/group/shadow resuelvan también contra SSSD (LDAP)
RUN sed -i \
        -e 's/^passwd:.*/passwd:         files sss/' \
        -e 's/^group:.*/group:          files sss/' \
        -e 's/^shadow:.*/shadow:         files sss/' \
        /etc/nsswitch.conf

COPY sssd.conf /etc/sssd/sssd.conf
COPY pam-common-auth /etc/pam.d/common-auth
COPY pam-common-account /etc/pam.d/common-account
COPY pam-common-session /etc/pam.d/common-session

RUN chmod 600 /etc/sssd/sssd.conf

# sshd: autenticación por contraseña vía PAM (que a su vez delega en SSSD/LDAP)
RUN sed -i \
        -e 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' \
        -e 's/^#\?UsePAM.*/UsePAM yes/' \
        -e 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication yes/' \
        /etc/ssh/sshd_config

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
