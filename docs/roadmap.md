# Hoja de ruta

Tres sprints de dos semanas. Cada uno cierra con una versión menor publicada y deja el repositorio
en un estado coherente por sí solo: si el siguiente se demora, lo anterior igual sirve.

El orden no es arbitrario. Primero se endurece lo que ya existe, porque todo lo que venga después
hereda esa base. Después se amplía dónde se puede recibir, que es por donde entra casi todo el que
adopta el paquete. Al final se completa la emisión, que es lo que más diseño nuevo pide.

Las reglas de [CONTRIBUTING.md](../CONTRIBUTING.md) valen para cada ítem: un cambio de
comportamiento empieza en la especificación y en los vectores, llega a los dos paquetes en el mismo
pull request y una decisión de diseño nueva es un archivo nuevo en [`adr/`](adr/).

| Sprint | Tema | Qué cambia para quien usa el paquete |
|---|---|---|
| 1 | Base sólida | Nada se rompe; hay más garantías comprobadas y límites explícitos |
| 2 | Recibir en más lugares | Más frameworks, más emisores, más almacenes y ayudas para probar |
| 3 | Emitir de punta a punta | De «un intento» a una entrega completa, observable y operable |

## Sprint 1: base sólida

**Estado: hecho, salvo lo que se indica abajo como pendiente.**

**Objetivo.** Que el repositorio cumpla las prácticas habituales de un paquete de seguridad
publicado, y que los límites que hoy quedan implícitos pasen a estar en la especificación.

### Cadena de suministro

- **Actualización automática de dependencias**, agrupada por ecosistema (npm, uv y las acciones del
  workflow), con las acciones siempre fijadas por hash como hasta ahora.
- **Análisis estático de seguridad** en cada pull request y en `main`, para TypeScript y Python.
- **Evaluación periódica de prácticas de seguridad del repositorio** con
  [OpenSSF Scorecard](https://scorecard.dev/), con el resultado publicado como insignia en el
  README.
- **Atestaciones de procedencia en los dos registros**, pedidas de forma explícita en el workflow
  de publicación, y un SBOM por paquete adjunto a cada versión.
- **Revisión de dependencias en el pull request**: falla si entra una dependencia con una
  vulnerabilidad conocida o con una licencia incompatible con MIT.

### Pruebas más duras

- **Pruebas basadas en propiedades** para lo que interpreta entrada ajena: las cabeceras con pares,
  la gramática de la URL de destino, las direcciones IP, `retry-after` y los secretos. La propiedad
  mínima es que nunca se lanza una excepción y que el resultado siempre es uno de los definidos.
- **Fuzzing diferencial programado.** La prueba de interoperabilidad ya compara los dos paquetes
  con variaciones al azar; pasa a correr cada noche con semilla nueva y muchas más rondas, y una
  diferencia abre un issue con la semilla para reproducirla. La primera corrida larga encontró
  una: una etiqueta `xn--` que no es Punycode válido pasa la gramática de la URL de destino, y
  el analizador de una de las plataformas la rechaza. No sale ningún pedido, así que hoy se
  acepta como falla segura. **Pendiente:** decidir en la especificación si esa URL debe ser
  `invalid_url`.
- **Umbral de cobertura también para los adaptadores**, no sólo para el dominio y la aplicación.
- **Matriz de entornos de ejecución.** Una prueba de humo que sólo usa APIs web recorre un ciclo
  completo en Deno y en Bun, además de Node. **Pendiente:** lo mismo dentro de un Worker.

### Límites explícitos en la especificación

- **Tamaño máximo del cuerpo al recibir.** Un resultado nuevo, con estado 413 sugerido, que se
  decide antes de calcular la firma. El límite es configurable y tiene un valor por defecto.
- **Tamaño máximo del payload al emitir**, con un valor por defecto conservador: los payloads
  chicos son la recomendación del formato de salida.
- **La respuesta del destino no se lee más allá de lo necesario.** Queda escrito que el cuerpo de
  la respuesta se descarta o se lee hasta un tope, para que un destino no pueda agotar memoria.
- **Cabecera `user-agent` propia al emitir**, con el nombre y la versión del paquete, para que
  quien recibe pueda identificar el tráfico. Entra a las cabeceras que quien integra no puede
  reemplazar.

### Salud del proyecto

- Plantillas de issue (error, esquema nuevo, pregunta) y de pull request con la lista de
  [CONTRIBUTING.md](../CONTRIBUTING.md).
- Código de conducta y archivo de responsables de revisión.
- Política de compatibilidad escrita: qué es API pública, qué versiones de Node y de Python se
  soportan y por cuánto tiempo, y cómo se anuncia una deprecación antes de la 1.0.

**Hecho cuando:** la evaluación de seguridad del repositorio no marca nada pendiente que dependa
del código, el fuzzing nocturno lleva una semana sin diferencias, y los cuatro límites tienen
sección en la especificación, vectores y adaptador en los dos paquetes.

## Sprint 2: recibir en más lugares

**Objetivo.** Que integrar la recepción sea una línea en el framework que ya se usa, con el emisor
que ya se tiene, y que probar esa integración no exija escribir la firma a mano.

**Estado: en curso.** Cada ítem dice si está hecho o pendiente.

### Adaptadores de entrada

El problema que resuelven es siempre el mismo y ya está nombrado en la
[guía para recibir](recibir.md): llegar al cuerpo crudo. Cada adaptador es un módulo de entrada
aparte, sin dependencia obligatoria.

- **Hecho. TypeScript:** `IncomingMessage` y `ServerResponse` de Node (cubre los frameworks
  montados sobre ellos) y una ayuda para los frameworks que ya entregan el cuerpo como `Buffer`.
- **Hecho. Python:** WSGI (cubre Flask y cualquier otro) y Django.
- **Hecho. Ejemplos ejecutables** en [`examples/`](../examples/): `node:http`, WSGI, Starlette y
  Django. La integración continua levanta cada uno y le manda un evento firmado, el mismo
  repetido y uno con otro secreto. **Pendiente:** uno para la API Fetch dentro de un Worker, que
  va junto con la prueba de humo en Workers del sprint 1.

### Esquemas de firma

- **Hecho. Firma asimétrica del formato estándar** para verificar. Es la variante vigente del
  formato, `v2a` (Ed25519 sobre el SHA-256 del contenido, con el identificador del destino
  adelante); la anterior, `v1a`, está obsoleta y no se implementa. Es un esquema aparte,
  `standard-v2a`, y en Python usa `cryptography` como dependencia opcional. Ver la
  [decisión 0007](adr/0007-firma-asimetrica.md).
- **Tres de cuatro hechos. Cuatro emisores más**, elegidos por demanda y por cubrir variantes que
  hoy no están. Hechos: marca de tiempo en cabecera separada con prefijo de versión (Slack), HMAC
  en base64 sobre el cuerpo (Shopify) y clave pública por emisor (Discord). Pendiente: firma
  sobre la URL más los parámetros, que pide guardar la URL completa en el pedido entrante y usa
  HMAC-SHA1. Cada uno entra por [el camino de siempre](agregar-un-esquema.md), citando la
  documentación pública del emisor.
- **Hecho. Varios emisores en una misma ruta.** Un verificador compuesto que elige el esquema por las
  cabeceras presentes y que rechaza como `ambiguous` un pedido que coincide con más de uno.

### Almacenes de reservas

- **Hecho. Redis.** Cada operación es un script y las entradas se borran solas. Los dos paquetes
  corren los mismos scripts y pasan el contrato de almacén contra un Redis de verdad.
- **Pendiente. Almacenes clave-valor con vencimiento** (el de Workers y DynamoDB). El de Workers
  no tiene escritura condicional: hay que documentar qué garantía pierde.

### Ayudas para probar

- **Hecho. Un módulo de pruebas por paquete** (`omniwebhook/testing`, `omniwebhook.testing`) que arma un
  pedido firmado válido para cualquier esquema, y sus variantes inválidas: vencido, con firma
  alterada, repetido. Sale de las mismas reglas que el generador de vectores.
- **Hecho. Una línea de comandos mínima**, la misma en los dos paquetes: firmar un cuerpo,
  verificar un pedido guardado y mandar un pedido firmado a una URL local. Lo que firma una lo
  verifica la otra.

### Lo que pasa después de verificar

- **Pendiente. Validación opcional del payload.** El evento verificado acepta un validador que cumpla la
  interfaz común de esquemas de cada ecosistema, sin atarse a una librería. Un payload que no
  valida es un resultado propio, distinto de `failed`, y no libera la reserva: reintentar no lo
  va a arreglar.
- **Hecho. Puerto de observación** de la recepción: quien integra recibe cada resultado con su
  duración y la clave del evento, sin secretos ni cuerpos. Es la base de la telemetría del
  sprint 3. Para la emisión no hizo falta: el registro de entregas ya recibe cada intento.

**Hecho cuando:** cada adaptador y cada esquema nuevo tienen vectores, los ejemplos corren en la
integración continua, y la prueba de interoperabilidad cubre la firma asimétrica en los dos
sentidos.

## Sprint 3: emitir de punta a punta

**Objetivo.** Hoy el paquete resuelve un intento y dice cuándo toca el siguiente. Este sprint
agrega, como piezas opcionales, lo que hace falta para operar entregas en producción sin
reescribirlo en cada proyecto.

### De un intento a una entrega

- **Bandeja de salida transaccional.** Un puerto y su tabla, compartida entre paquetes como las
  otras, para encolar un mensaje en la misma transacción que el cambio de negocio que lo origina.
  Es la forma estándar de no perder un evento ni emitir uno de un cambio que no se confirmó.
- **Despachador de referencia.** Un caso de uso que toma lo pendiente que ya venció, lo entrega y
  registra el resultado, con toma exclusiva para que varios procesos no entreguen lo mismo. No
  trae planificador: se llama desde un cron, una cola o un bucle. Reemplaza la frase «programarlo
  es responsabilidad de quien integra» por una pieza que se puede usar o no, y pide una decisión
  de arquitectura.
- **Orden y concurrencia por destino.** Un tope de entregas simultáneas por destino, para no
  tumbar a un receptor lento.

### Salud de los destinos

- **Deshabilitación automática.** La especificación define cuándo un destino se considera caído
  (fallos consecutivos durante una ventana, o un `gone`) y el despachador deja de intentar. El
  paquete calcula el estado a partir del registro; avisarle al dueño del destino sigue siendo de
  quien integra, y queda un punto de extensión para hacerlo.
- **Rehabilitación y reenvío.** Reactivar un destino y reenviar lo que falló mientras estuvo
  caído, por rango de tiempo, con el mismo `id` de mensaje.

### Suscripciones

- **Tipos de evento.** El mensaje lleva un tipo con forma `grupo.accion`, y un destino declara a
  cuáles se suscribe, con comodín por grupo. El filtrado es una función pura del dominio, con
  vectores.
- **Catálogo de eventos.** Los tipos se declaran con su esquema de payload, y de ahí sale un
  documento [OpenAPI](https://www.openapis.org/) con la sección `webhooks`, para que quien recibe
  genere sus tipos.

### Firma y transporte

- **Firma asimétrica al emitir**, con la misma pieza que el sprint 2 agregó para verificar. Quien
  recibe guarda una clave pública y no un secreto compartido.
- **Rotación con fecha.** Un secreto anterior deja de firmar solo después de un plazo, en vez de
  depender de que alguien lo quite de la lista.

### Observabilidad

- **Telemetría con [OpenTelemetry](https://opentelemetry.io/)** sobre el puerto de observación:
  una traza por intento, con los nombres de atributos de las convenciones semánticas de HTTP, y
  métricas de intentos por clase, duración y entregas agotadas. Es un adaptador opcional.
- **Propagación del contexto de traza** en una cabecera `traceparent`, para que la entrega se vea
  como continuación de la operación que la originó.

### Documentación para llegar a la 1.0

- **Documentación en inglés** además de la de español, con la especificación como primera pieza
  traducida y el comprobador de ejemplos cubriendo los dos idiomas.
- **Sitio de documentación** generado desde el repositorio, con referencia de la API extraída de
  los tipos.
- **Guía para implementar la especificación en otro lenguaje**, con los vectores publicados como
  artefacto versionado para consumirlos sin clonar el repositorio.
- **Criterios de la 1.0** escritos: qué tiene que estar estable, y qué queda afuera.

**Hecho cuando:** un ejemplo completo encola dentro de una transacción, entrega con el
despachador, deshabilita un destino caído y muestra la traza de punta a punta; y la prueba de
interoperabilidad comprueba que un paquete despacha lo que encoló el otro.

## Lo que queda afuera

- **Un servicio para desplegar.** El paquete es una librería: no trae servidor, panel ni API de
  administración.
- **Un planificador o una cola propios.** El despachador se apoya en lo que ya se use.
- **Un tercer lenguaje.** La guía y los vectores publicados lo dejan preparado, pero no entra en
  estos tres sprints.
- **Un modo que saltee la verificación.** Ni para desarrollo: para eso están las ayudas de prueba.
