# Componente: c2-target

Contenedor pasivo (`nginx:alpine` sirviendo `index.html`) que representa, solo a efectos de la
demo, el destino de red "malicioso" citado en la alerta (IP de C2 / almacenamiento de exfiltración).

No ejecuta ningún ataque ni recibe ningún dato real — su único propósito es tener algo contra lo
que `victim-host` pueda intentar conectarse (`curl`), para poder demostrar el efecto antes/después
del bloqueo aplicado por el contenedor `firewall`.

No requiere Dockerfile propio: se define directamente en `docker-compose.yml` montando `index.html`.
