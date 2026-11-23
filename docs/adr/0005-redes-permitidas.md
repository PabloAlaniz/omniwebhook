# 0005. Redes permitidas explícitas, sin habilitar nunca los metadatos de la nube

- Estado: aceptada
- Fecha: 2026-11-23

## Contexto

La política de URLs bloquea los rangos privados, locales y reservados. Es lo correcto cuando los
destinos los registran terceros, pero deja afuera un caso común: un producto instalado por su
propio usuario (self-hosted) que tiene que entregar a servicios de la misma máquina o la misma red
local, como una herramienta de automatización en otro contenedor.

Sin una opción en el paquete, quien integra tiene dos salidas malas: un resolver falso que
esconde las direcciones reales, o un transporte que ignora la dirección validada. Las dos apagan
la política entera, no sólo para la red que hacía falta.

## Decisión

1. La configuración del emisor acepta una lista de redes permitidas, vacía por defecto. Una
   dirección bloqueada que cae en una red de la lista se acepta.
2. Las redes se escriben `dirección/prefijo` con una forma estricta: la misma gramática de
   direcciones de la sección 8.1, prefijo decimal sin ceros a la izquierda y bits fuera del
   prefijo en cero. Una red mal escrita es un error de configuración al construir, no un rechazo
   en cada intento.
3. Los servicios de metadatos de las nubes (`169.254.0.0/16`, `100.100.100.200/32`,
   `fd00:ec2::254/128`) no se permiten nunca. Son el blanco más valioso de un ataque de este tipo
   y ningún uso legítimo de un webhook los necesita.
4. Una IPv6 que envuelve una IPv4 se sigue evaluando por la IPv4, y una red IPv6 dentro de
   `::ffff:0:0/96` no se acepta, porque nunca coincidiría.

## Consecuencias

- Una instalación propia puede entregar a su red sin desactivar el resto de la política: la forma
  de la URL, las credenciales, el esquema y la conexión a la dirección validada siguen igual.
- Permitir `0.0.0.0/0` es posible y queda a cargo de quien lo configura; los metadatos de la nube
  siguen bloqueados igual.
- La lista de direcciones que nunca se permiten es parte de la especificación: agregar una es un
  cambio de la especificación, con sus vectores.
