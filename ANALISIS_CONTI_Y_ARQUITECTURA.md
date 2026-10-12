# Análisis del ataque Conti (variante Linux) y arquitectura de la solución SOAR

## 1. El ataque analizado: Ransomware Conti — variante Linux

### 1.1 Contexto

Conti fue uno de los grupos de ransomware-as-a-service (RaaS) más activos y mejor documentados
entre 2020 y 2022, vinculado a la infraestructura de los troyanos **TrickBot** y **BazarLoader**
como vectores de acceso inicial habituales. Operaba bajo el modelo de **doble extorsión**: exfiltraba
datos antes de cifrarlos, y amenazaba con publicarlos si la víctima no pagaba, además del propio
cifrado. El grupo se disolvió formalmente a mediados de 2022, poco después de la filtración interna
de sus chats y código fuente ("Conti Leaks", febrero 2022), que es una de las fuentes que permite
un análisis técnico tan detallado de sus TTPs reales.

La **variante Linux**, desarrollada en 2021-2022, es particularmente relevante para este proyecto
porque estaba orientada a **servidores críticos e infraestructura de virtualización** (en particular
hosts ESXi de VMware), ampliando el impacto del ataque más allá de estaciones de trabajo Windows.
Usaba cifrado ChaCha8 y, para la exfiltración previa al cifrado, se apoyaba fuertemente en
**Rclone** hacia almacenamiento en la nube (Mega, en algunos casos S3), precisamente porque son
servicios legítimos con reputación de red limpia.

### 1.2 Kill Chain resumido

| Fase | Descripción en el caso Conti (variante Linux) |
|---|---|
| Reconocimiento / Entrega | Phishing dirigido a un administrador de sistemas con credenciales privilegiadas |
| Explotación / Instalación | Uso de las credenciales comprometidas para acceso SSH al servidor Linux |
| C2 y movimiento lateral | Canal C2 desde el servidor comprometido, enumeración de la red interna |
| Escalamiento | Abuso de credenciales/vulnerabilidades locales para obtener root |
| **Exfiltración** | **Rclone hacia almacenamiento en la nube externo — punto donde arranca este playbook** |
| Impacto | Cifrador Conti Linux (ChaCha8), cifrado masivo de archivos críticos |

El playbook de este proyecto arranca deliberadamente en la fase de **Exfiltración**, por indicación
explícita del profesor del curso — y tiene además justificación técnica propia: es la última
oportunidad de contención antes de que ocurra el daño irreversible (el cifrado, fase de Impacto).

## 2. Marcos de referencia utilizados

Es importante ser precisos sobre qué partes de este diseño provienen de una fuente publicada
verificable, y cuáles son decisiones de arquitectura propias del equipo.

### 2.1 Fuentes específicas de Conti (verificables)

- **CISA AA21-265A** — "Conti Ransomware", advisory conjunto de CISA/FBI/NSA. Es la fuente de los
  TTPs, IOCs y técnicas MITRE ATT&CK específicas de Conti usadas en este proyecto (incluyendo el uso
  documentado de Rclone para exfiltración). Buscar el código **AA21-265A** directamente en
  cisa.gov/news-events/cybersecurity-advisories/ para verificarlo — el código de alerta es el
  identificador estable, independiente de cambios de URL.
- **MITRE ATT&CK — Software S0575 (Conti)**: `https://attack.mitre.org/software/S0575/` — cataloga
  las técnicas ATT&CK específicamente asociadas a Conti (T1486 Data Encrypted for Impact, T1567.002
  Exfiltration to Cloud Storage, T1078 Valid Accounts, T1021.004 Remote Services: SSH, entre otras),
  que es lo que se usó para el mapeo técnica-por-técnica de este proyecto.

### 2.2 Marcos genéricos de respuesta a incidentes (no específicos de Conti)

- **NIST SP 800-61 Rev. 2** — "Computer Security Incident Handling Guide":
  `https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-61r2.pdf` — de acá se toman las
  fases genéricas (Preparación → Detección y Análisis → Contención/Erradicación/Recuperación →
  Post-Incidente) usadas para estructurar el ciclo de vida general de la respuesta.

### 2.3 Aclaración importante

**No se encontró ni se utilizó un playbook publicado específico de Conti que prescriba paso a paso
la secuencia exacta de contención implementada acá** (deshabilitar cuenta LDAP → bloquear IP →
aislar host vía EDR, con las condiciones y umbrales concretos usados). Ni CISA AA21-265A ni el
MITRE ATT&CK software entry de Conti son playbooks de respuesta — son catálogos de TTPs/IOCs y
mitigaciones generales (segmentación de red, MFA, backups offline, parcheo), no procedimientos de
respuesta automatizada paso a paso.

La **secuencia, las condiciones y los umbrales concretos de este playbook son diseño propio del
equipo**, construido aplicando: (a) las técnicas y el punto del kill chain específicos de Conti
documentados en las fuentes de la sección 2.1, (b) la estructura de fases genérica de NIST 800-61,
y (c) principios generales de ingeniería de seguridad (respuesta proporcional al radio de impacto,
aprobación humana para acciones de alto impacto) que no provienen de un documento único citable,
sino de la práctica estándar de diseño de SOAR/IR descrita de forma general en la bibliografía del
curso.

## 3. Decisiones de diseño

### 3.1 El enriquecimiento es de apoyo, no determinante

VirusTotal (hash) y AbuseIPDB (reputación de IP) no son pruebas concluyentes de que algo sea
malicioso — son señales de confianza que se suman a una alerta que ya viene de una detección de
comportamiento de alta severidad (Rclone en fase de Exfiltración). Esto es especialmente relevante
para Conti: es un actor dirigido y sofisticado que, según los propios chats filtrados en Conti Leaks,
prueba sus binarios contra motores antivirus antes de desplegarlos, y usa infraestructura de nube
legítima (Mega, S3) precisamente porque tiene reputación limpia. Por diseño, es esperable que un
ataque real de Conti pueda no matchear en ninguna de las dos fuentes de enriquecimiento — la alerta
original (comportamiento, no reputación) sigue siendo la señal primaria.

### 3.2 Respuesta graduada según radio de impacto

No todas las acciones de contención tienen el mismo costo si se disparan sobre un falso positivo.
Se diseñó la exigencia de confianza de cada acción proporcional a su radio de impacto:

| Acción | Radio de impacto | Exigencia de confianza |
|---|---|---|
| Firewall (bloqueo de IP puntual) | Bajo — no afecta el resto del tráfico del host | Se aplica siempre, sin condicionar al enriquecimiento |
| LDAP (deshabilitar cuenta) | Medio — afecta una identidad específica, reversible | Requiere al menos una señal de enriquecimiento confirmada (OR) |
| Wazuh (aislamiento total del host) | **Alto** — corta todo el tráfico; si el host fuera un servidor de producción, implica una caída total del servicio | Requiere señal de enriquecimiento **y** aprobación humana explícita antes de ejecutarse |

Esta gradación es la razón por la que el aislamiento total vía Wazuh queda detrás de un nodo de
**tarea manual (User Input)** — es la acción con mayor potencial de daño al negocio si se ejecuta
sobre un falso positivo, así que no se automatiza por completo.

## 4. Arquitectura de la solución

Laboratorio contenerizado en tres capas (ver `README.md` del repositorio para el detalle completo
de cada nodo):

```
nodos-organizacion/     ← activos reales de la empresa hipotética
  ldap-server/             openldap + phpldapadmin + wrapper HTTP (acción de contención LDAP)
  victim-host/             servidor Linux con sshd/sssd + agente Wazuh (nunca se ataca)
  firewall-perimetral/     API + iptables (bloqueo real de red)

infraestructura-soc/    ← seguridad centralizada, no "por servidor"
  wazuh-manager/           EDR manager, usado solo como actuador de Active Response
  shuffle/                 SOAR self-hosted (vendorizado, incluido en el compose raíz)
  alert-injector/          script que sustituye a la capa de SIEM (fuera de alcance del proyecto)

lab-props/              ← no existen en la organización real
  c2-target/               destino de red de prueba
```

## 5. Detalle final del playbook en Shuffle

```
Webhook (Trigger)
   │  (un trigger solo admite 1 conexión de salida)
   ▼
VirusTotal_v3_1  (enriquecimiento por hash)
   │
   ├──────────────────────────────────────────┐
   ▼ (secuencial, siempre)                     ▼ (siempre, sin condición)
AbuseIPDB_v2_1  (enriquecimiento por IP)     Firewall — bloquear IOC
   │
   ├──(secuencial, siempre)──▶ Discord — notificación del caso
   │
   ├──(si malicious>0 OR abuseConfidenceScore>50)──▶ LDAP — deshabilitar cuenta
   │
   └──(si malicious>0 OR abuseConfidenceScore>50)──▶ User Input — autorizar aislamiento
                                                          │
                                                          ▼ (secuencial)
                                                     Wazuh — autenticar
                                                          │
                                                          ▼ (secuencial)
                                                     Wazuh — aislar host (isolate-host0)
```

Condición usada en las dos ramas condicionales (LDAP y User Input):
```
$virustotal_v3_1.body.data.attributes.last_analysis_stats.malicious > 0
OR
$abuseipdb_v2_1.body.data.abuseConfidenceScore > 50
```

El Firewall se conecta secuencialmente desde `VirusTotal_v3_1` (no desde el Webhook) porque el
nodo Trigger solo admite una conexión de salida, y esa ya está usada hacia VirusTotal. Se activa
siempre, sin condición, dado su bajo radio de impacto (ver sección 3.2).

### 5.1 Mensaje final de Discord (notificación del caso)

```json
{
  "content": "🚨 **Incidente de seguridad detectado — Ransomware Conti (fase Exfiltración)**\n\n**Host afectado:** $exec.agent.name\n**Usuario:** $exec.data.srcuser\n**IP destino (C2/exfiltración):** $exec.data.dst_ip\n**Técnica MITRE ATT&CK:** $exec.rule.mitre.id\n\n**Resultado VirusTotal:** $virustotal_v3_1.body.data.attributes.last_analysis_stats.malicious motores detectaron el hash como malicioso\n**Resultado AbuseIPDB:** score de confianza de abuso = $abuseipdb_v2_1.body.data.abuseConfidenceScore/100\n\nSe iniciaron las acciones de contención automática correspondientes."
}
```

### 5.2 Nodo User Input — configuración final

- **Name**: `Aprobar_Aislamiento_Wazuh`
- **Information** (Markdown, mostrado al analista):
```
## ¿Autorizar aislamiento total del host?

**Host:** $exec.agent.name
**Usuario comprometido:** $exec.data.srcuser (ya deshabilitado en LDAP)
**IP de exfiltración:** $exec.data.dst_ip (ya bloqueada puntualmente en firewall)

**VirusTotal:** $virustotal_v3_1.body.data.attributes.last_analysis_stats.malicious motores detectaron el hash como malicioso
**AbuseIPDB:** score de abuso = $abuseipdb_v2_1.body.data.abuseConfidenceScore/100

Esta acción corta TODO el tráfico de red del host (no solo hacia la IP de exfiltración) hasta que se revierta manualmente. Confirmar si se autoriza continuar con la autenticación contra Wazuh y el aislamiento.
```
- **Input options**: sin canal externo configurado (Email/SMS/Subflow) — la aprobación se realiza
  directamente desde el panel de Shuffle durante la demo.
- **Required Input-Questions**: `aprobacion` (Sí/No) — queda registrada la decisión del analista en
  el caso. *(Mejora pendiente para producción: condicionar la ejecución de los nodos siguientes a
  que la respuesta sea "Sí"; en esta versión los nodos de Wazuh corren secuencialmente después de
  cualquier respuesta.)*

## 6. Validación end-to-end

El playbook descrito arriba no quedó solo en el diseño — se construyó en Shuffle y se corrió de
punta a punta contra los contenedores reales del laboratorio. Resultado de la ejecución de
validación final:

- **Estado de la ejecución**: `FINISHED`, con los **8 nodos en `SUCCESS`**
  (`Virustotal_v3_1`, `AbuseIPDB_v2_1`, `firewall`, `ldap`, `Aprobar_Aislamiento`, `Discord_1`,
  `wazuh`, `wazuh_2`).
- **LDAP**: antes de la ejecución, `ssh testuser@victim-host` autenticaba con éxito; después,
  falla (`Permission denied`) — la cuenta quedó deshabilitada de verdad en el directorio, no solo
  en la respuesta HTTP.
- **Firewall**: se insertó una regla real (`DROP` en la cadena `DOCKER-USER`) entre `victim-host` y
  la IP de exfiltración del payload — verificado con `GET /rules` del contenedor `firewall`.
- **Aprobación humana**: la ejecución quedó genuinamente pausada en estado `WAITING` en el nodo
  `Aprobar_Aislamiento` hasta que se aprobó manualmente — los nodos de Wazuh no se ejecutaron hasta
  ese momento, confirmando que el gate de aprobación no es solo decorativo.
- **Wazuh (aislamiento total)**: tras la aprobación, `victim-host` dejó de poder alcanzar
  absolutamente cualquier destino de red (incluido `c2-target`, que no tiene relación con la IP de
  exfiltración del payload) — a diferencia del bloqueo puntual del firewall, que solo afectaba la
  IP específica del IOC. El agente siguió reportando `active` en `GET /agents` de Wazuh, confirmando
  que el aislamiento no rompió la gestión del EDR.

Esto confirma en la práctica la premisa central del diseño (sección 3.2): las tres acciones de
contención tienen efectos de distinto alcance, y el playbook las trata de forma proporcionalmente
distinta — desde el bloqueo más quirúrgico (firewall, siempre activo) hasta el más disruptivo
(aislamiento EDR, con aprobación humana obligatoria).
