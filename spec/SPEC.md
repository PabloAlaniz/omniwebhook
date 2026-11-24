# Especificación de omniwebhook

Versión de la especificación: `0` (ver [`VERSION`](VERSION)). Hasta la versión `1` puede cambiar
entre versiones menores de los paquetes.

Este documento define el comportamiento que comparten todos los paquetes. Los vectores de
[`vectors/`](vectors/) lo vuelven verificable: un paquete cumple la especificación si pasa todos.

Las palabras DEBE, NO DEBE, DEBERÍA y PUEDE se usan con el sentido habitual de los documentos
normativos.

## 1. Las dos reglas

1. **Nada se procesa sin verificar.** No existe configuración que saltee la verificación. Sin un
   secreto utilizable, el resultado es un rechazo. Cuando el esquema lleva una marca de tiempo
   firmada, comprobar que es reciente es parte de verificar y no se puede desactivar.
2. **Cada evento produce efecto una sola vez.** El evento se reserva antes de procesarlo. Si el
   procesamiento falla, la reserva se libera para que el reintento del emisor pueda procesarlo.

## 2. Términos

- **Emisor**: quien envía el webhook. **Receptor**: quien lo recibe.
- **Cuerpo crudo**: los bytes del cuerpo HTTP tal como llegaron, antes de interpretarlos.
- **Esquema**: un formato de firma. Cada esquema sabe verificar y dice cuál es la clave del evento.
- **Clave del evento**: el texto que identifica un evento para no procesarlo dos veces.
- **Ahora**: el tiempo actual en segundos desde la época Unix. Siempre llega inyectado.

## 3. Pedido entrante

Un pedido entrante tiene:

- `headers`: nombres sin distinguir mayúsculas. Un nombre puede traer más de un valor.
- `query`: los parámetros de la URL. Un nombre puede traer más de un valor.
- `body`: el cuerpo crudo, en bytes.

Un valor de cabecera o de parámetro se usa sin espacios al principio ni al final. Un valor vacío
después de recortarlo equivale a que el dato no esté.

En todo este documento, «espacio» es el carácter de espacio (U+0020) o la tabulación (U+0009), y
nada más. Cualquier otro carácter, aunque se vea en blanco, es parte del valor.

## 4. Resultado de la verificación

Verificar nunca lanza una excepción por culpa del pedido. Devuelve uno de estos resultados:

| Resultado | Significado |
|---|---|
| `ok` | La firma es válida y, si el esquema lleva marca de tiempo, es reciente |
| `unconfigured` | No hay secretos, o alguno no se puede usar |
| `missing` | Falta una cabecera o un parámetro que el esquema exige |
| `ambiguous` | Un dato que debe ser único llegó repetido |
| `malformed` | Un dato está pero no tiene la forma esperada |
| `invalid` | Ninguna firma coincide |
| `stale` | La firma es válida pero la marca de tiempo está fuera de la tolerancia |

Con `ok` el resultado trae además `event_key` (siempre) y `timestamp` (en segundos, o nulo si el
esquema no lleva marca de tiempo).

### 4.1. Orden de las comprobaciones

Las comprobaciones se hacen en este orden y se devuelve la primera que falla:

1. `unconfigured`
2. `missing`
3. `ambiguous`
4. `malformed`
5. `invalid`
6. `stale`

La frescura se evalúa al final: `stale` sólo se informa de un pedido cuya firma es válida.

### 4.2. Secretos

- Cada esquema recibe una lista de secretos. La firma es válida si coincide con cualquiera de
  ellos; así se rota un secreto sin cortar el servicio.
- Una lista vacía, un secreto vacío o un secreto que el esquema no puede interpretar dan
  `unconfigured` para todos los pedidos. Alcanza con que uno de la lista sea inutilizable.
- Un secreto NO DEBE aparecer en un resultado, un error ni un log.

### 4.3. Comparación de firmas

- La firma esperada se codifica como texto y se compara con la recibida en tiempo constante.
- En hexadecimal, la esperada va en minúsculas y la recibida se pasa a minúsculas antes de comparar.
- En base64 se usa el alfabeto estándar con relleno y la comparación es exacta.
- Una firma recibida con otra forma simplemente no coincide. No es un error aparte.

### 4.4. Frescura

- La tolerancia se expresa en segundos. Por defecto es `300`.
- La tolerancia DEBE ser un entero mayor que cero. Un valor inválido es un error de configuración
  al construir el esquema, no un resultado.
- Un pedido es `stale` si `|ahora - marca| > tolerancia`. Vale igual para una marca en el pasado
  que en el futuro.
- Los esquemas sin marca de tiempo firmada no pueden comprobar frescura. En ellos la protección
  contra la repetición es la reserva del evento (sección 6).

### 4.5. Datos repetidos

Es `ambiguous`:

- una cabecera o un parámetro que el esquema usa y llega con más de un valor;
- dentro de una cabecera con pares `clave=valor`, una clave que debe ser única y aparece más de
  una vez.

Un verificador NO DEBE elegir uno de los valores repetidos.

### 4.5.1. Cabeceras con pares

Una cabecera con pares `clave=valor` se parte por comas. Cada parte se divide en el primer `=` y se
recortan los espacios de la clave y del valor. Una parte sin `=`, con la clave vacía o con el valor
vacío se ignora.

### 4.6. Clave del evento

- La clave siempre empieza con el nombre del esquema y `:`.
- Cuando el esquema no encuentra un identificador, usa la huella del cuerpo:
  `<esquema>:sha256:<SHA-256 del cuerpo crudo en hexadecimal en minúsculas>`.
- Quien integra PUEDE reemplazar la clave por una propia calculada a partir del pedido verificado.

### 4.7. Varios esquemas en una ruta

Un verificador compuesto atiende en una misma URL a más de un emisor. Recibe una lista de rutas;
cada ruta es el nombre de una cabecera y un verificador.

- Una ruta coincide con un pedido si su cabecera llega con al menos un valor que no sea vacío
  (sección 3).
- Si no coincide ninguna ruta, el resultado es `missing`.
- Si coincide más de una, el resultado es `ambiguous`. NO DEBE elegirse una, ni siquiera cuando
  sólo una de las firmas resultaría válida.
- Si coincide exactamente una, el resultado es el de su verificador, sin cambios.

Un pedido NO DEBE probarse contra un esquema después de otro hasta que alguno lo acepte: eso le
daría a quien manda el pedido la posibilidad de elegir con qué reglas se lo verifica.

Una lista de rutas vacía, una cabecera vacía o una cabecera repetida entre rutas (sin distinguir
mayúsculas) es un error de configuración al construirlo, no un resultado.

## 5. Esquemas

Todos usan HMAC-SHA256, salvo `standard-v2a` (sección 5.10) y `discord` (sección 5.11), que
verifican con una clave pública.
«Cuerpo» es siempre el cuerpo crudo.

### 5.1. `standard`

El formato [Standard Webhooks](https://www.standardwebhooks.com/), con firma simétrica `v1`.

- Cabeceras exigidas: `webhook-id`, `webhook-timestamp`, `webhook-signature`.
- Secreto: el prefijo `whsec_` es opcional; el resto es base64 y, decodificado, es la clave. Es
  utilizable si, sin el prefijo, no está vacío, su largo es múltiplo de cuatro y cumple
  `^[A-Za-z0-9+/]*={0,2}$`.
- `webhook-timestamp` DEBE cumplir `^[0-9]{1,11}$`. Si no, `malformed`.
- `webhook-signature` trae una o más firmas separadas por espacios. Sólo cuentan las que empiezan
  con `v1,`; el resto se ignora. Si no hay ninguna `v1,`, `malformed`.
- Contenido firmado: `<webhook-id>.<webhook-timestamp>.<cuerpo>`.
- Firma: base64 del HMAC.
- Marca de tiempo: `webhook-timestamp`, en segundos.
- Clave del evento: `standard:<webhook-id>`.

Este es además el esquema con el que se firma lo que se emite (sección 7).

### 5.2. `stripe`

- Cabecera exigida: `stripe-signature`, con pares `clave=valor` (sección 4.5.1).
- Cuentan las claves `t` y `v1`. Cualquier otra se ignora.
- Sin `t` o sin ningún `v1`, `malformed`. Más de un `t`, `ambiguous`. Puede haber varios `v1`.
- `t` DEBE cumplir `^[0-9]{1,11}$`. Si no, `malformed`.
- Secreto: el texto completo, en UTF-8, es la clave.
- Contenido firmado: `<t>.<cuerpo>`.
- Firma: hexadecimal del HMAC. Es válida si coincide con cualquier `v1`.
- Marca de tiempo: `t`, en segundos.
- Clave del evento: `stripe:<id>`, donde `id` es el campo `id` del cuerpo si el cuerpo es un objeto
  JSON con un `id` de texto no vacío. Si no, la huella del cuerpo.
  El cuerpo se interpreta como JSON estricto en UTF-8: con una marca de orden de bytes al
  principio, o con valores que no son JSON como `NaN` o `Infinity`, se usa la huella. Con un
  anidamiento tan profundo que la plataforma no lo puede interpretar, también. El tamaño de un
  número no cambia el resultado.

### 5.3. `mercadopago`

- Cabecera exigida: `x-signature`, con pares `clave=valor` (sección 4.5.1). Las claves se
  comparan en minúsculas.
- Datos opcionales: la cabecera `x-request-id` y el parámetro `data.id` de la URL.
- Cuentan las claves `ts` y `v1`. Sin alguna de las dos, `malformed`. Cualquiera repetida,
  `ambiguous`.
- `ts` DEBE cumplir `^[0-9]{1,15}$`. Si no, `malformed`.
- Secreto: el texto completo, en UTF-8, es la clave.
- Contenido firmado (el «manifest»): se arman, en este orden y sólo si el dato está,
  `id:<data.id en minúsculas>`, `request-id:<x-request-id>` y `ts:<ts>`; se unen con `;` y se
  agrega un `;` final. Ejemplo: `id:123;request-id:abc;ts:1700000000;`.
- Firma: hexadecimal del HMAC.
- Marca de tiempo: `ts`. Un valor mayor o igual que `100000000000` está en milisegundos y se
  divide por mil descartando el resto; uno menor está en segundos.
- Clave del evento: `mercadopago:<data.id en minúsculas>:<x-request-id>`, con texto vacío en el
  lugar del dato que falte. Si faltan los dos, `mercadopago:ts:<ts>`.

La firma de este esquema **no cubre el cuerpo**. Quien procesa el evento DEBERÍA tratarlo como un
aviso de cambio y consultar el recurso al emisor, y PUEDE reemplazar la clave del evento por una
que incluya el tipo de aviso. Las notificaciones que el emisor no firma no se pueden verificar con
este esquema.

### 5.4. `github`

- Cabecera exigida: `x-hub-signature-256`, con la forma `sha256=<hexadecimal>`. Sin ese prefijo,
  `malformed`.
- Secreto: el texto completo, en UTF-8, es la clave.
- Contenido firmado: el cuerpo.
- Sin marca de tiempo.
- Clave del evento: `github:<x-github-delivery>` si la cabecera está. Si no, la huella del cuerpo.

### 5.5. `creem`

- Cabecera exigida: `creem-signature`, en hexadecimal.
- Secreto: el texto completo, en UTF-8, es la clave.
- Contenido firmado: el cuerpo.
- Sin marca de tiempo.
- Clave del evento: `creem:<id>`, con la misma regla del campo `id` que en `stripe`.

### 5.6. `tiktok`

- Cabecera exigida: `tiktok-signature`, con pares `clave=valor` (sección 4.5.1).
- Cuentan las claves `t` y `s`. Cualquier otra se ignora.
- Sin `t` o sin `s`, `malformed`. Cualquiera de las dos repetida, `ambiguous`.
- `t` DEBE cumplir `^[0-9]{1,11}$`. Si no, `malformed`.
- Secreto: el texto completo, en UTF-8, es la clave (el *client secret* de la app).
- Contenido firmado: `<t>.<cuerpo>`.
- Firma: hexadecimal del HMAC.
- Marca de tiempo: `t`, en segundos.
- Clave del evento: la huella del cuerpo. El emisor no manda un identificador de entrega y el cuerpo
  no trae un `id`; los reintentos llegan con el mismo cuerpo.

### 5.7. `hmac-body`

Un esquema genérico para emisores que firman sólo el cuerpo. Se configura con:

| Opción | Significado | Por defecto |
|---|---|---|
| `name` | El nombre del esquema en la clave del evento | `hmac-body` |
| `header` | La cabecera que trae la firma | obligatoria |
| `prefix` | Un texto fijo antes de la firma | vacío |
| `encoding` | `hex` o `base64` | `hex` |
| `id_header` | La cabecera que identifica el evento | ninguna |

- Si `prefix` no es vacío y el valor no empieza con él, `malformed`.
- Secreto: el texto completo, en UTF-8, es la clave.
- Contenido firmado: el cuerpo. Sin marca de tiempo.
- Clave del evento: `<name>:<valor de id_header>` si está configurada y llega. Si no, la huella
  del cuerpo.

### 5.8. `slack`

- Cabeceras exigidas: `x-slack-signature` y `x-slack-request-timestamp`.
- `x-slack-request-timestamp` DEBE cumplir `^[0-9]{1,11}$`. Si no, `malformed`.
- `x-slack-signature` DEBE empezar con `v0=`, tal cual. Si no, `malformed`. Lo que sigue es la
  firma.
- Secreto: el texto completo, en UTF-8, es la clave (el *signing secret* de la app).
- Contenido firmado: `v0:<x-slack-request-timestamp>:<cuerpo>`.
- Firma: hexadecimal del HMAC.
- Marca de tiempo: `x-slack-request-timestamp`, en segundos.
- Clave del evento: `slack:<event_id>`, con la regla del campo `id` de `stripe` aplicada al campo
  `event_id` del cuerpo. Los pedidos que no son eventos (comandos, interacciones) llegan como
  formulario y no traen ese campo: su clave es la huella del cuerpo.

### 5.9. `shopify`

- Cabecera exigida: `x-shopify-hmac-sha256`. Opcional: `x-shopify-webhook-id`.
- Secreto: el texto completo, en UTF-8, es la clave (el *client secret* de la app).
- Contenido firmado: el cuerpo.
- Firma: base64 del HMAC, con relleno. Se compara tal como llegó.
- Sin marca de tiempo.
- Clave del evento: `shopify:<x-shopify-webhook-id>` si llega. Si no, la huella del cuerpo. Ese
  identificador se repite en los reintentos de un mismo webhook.

### 5.10. `standard-v2a`

El formato [Standard Webhooks](https://www.standardwebhooks.com/) con firma asimétrica `v2a`
(Ed25519). Quien recibe guarda una clave pública: con ella puede verificar, pero no firmar.

Se configura con una lista de claves públicas y con el `endpoint_id`: el identificador que el
emisor le asignó a este destino al crearlo.

- Cabeceras exigidas: `webhook-id`, `webhook-timestamp`, `webhook-signature`.
- Clave pública: el prefijo `whpk_` es obligatorio; el resto es base64 y, decodificado, son los 32
  bytes de la clave. Es utilizable si, sin el prefijo, cumple `^[A-Za-z0-9+/]*={0,2}$`, su largo es
  múltiplo de cuatro y decodifica a exactamente 32 bytes. Las reglas de la sección 4.2 valen
  igual: una lista vacía o una clave inutilizable dan `unconfigured`.
- `endpoint_id` NO DEBE estar vacío ni contener `.`. Si no, es un error de configuración al
  construir el esquema. Nunca se toma del pedido.
- `webhook-timestamp` DEBE cumplir `^[0-9]{1,11}$`. Si no, `malformed`.
- `webhook-signature` trae una o más firmas separadas por espacios. Sólo cuentan las que empiezan
  con `v2a,`; el resto se ignora, incluidas las simétricas `v1,` y las de la versión anterior
  `v1a,`. Si no hay ninguna `v2a,`, `malformed`.
- Contenido firmado: los 32 bytes crudos de
  `SHA-256(<endpoint_id>.<webhook-id>.<webhook-timestamp>.<cuerpo>)`.
- Firma: base64, con relleno, de los 64 bytes de la firma Ed25519 (RFC 8032) de ese contenido.
- La firma es válida si alguna de las recibidas verifica con alguna de las claves. Una firma que
  no es base64 o que no tiene 64 bytes simplemente no verifica: no es un error aparte. Acá no
  aplica la comparación de texto de la sección 4.3.
- Marca de tiempo: `webhook-timestamp`, en segundos.
- Clave del evento: `standard:<webhook-id>`, la misma que con firma simétrica: es el mismo
  emisor y el mismo mensaje.

### 5.11. `discord`

Firma con Ed25519. Se configura con una lista de claves públicas: la de la aplicación.

- Cabeceras exigidas: `x-signature-ed25519` y `x-signature-timestamp`.
- Clave pública: 64 dígitos hexadecimales, en mayúsculas o minúsculas, que son los 32 bytes de la
  clave. Cualquier otra forma da `unconfigured`, con las reglas de la sección 4.2.
- `x-signature-timestamp` DEBE cumplir `^[0-9]{1,11}$`. Si no, `malformed`.
- Contenido firmado: `<x-signature-timestamp><cuerpo>`, sin separador.
- Firma: los 64 bytes de la firma Ed25519 (RFC 8032) de ese contenido, en hexadecimal, en
  mayúsculas o minúsculas. Una que no son 128 dígitos hexadecimales simplemente no verifica.
- Marca de tiempo: `x-signature-timestamp`, en segundos. El emisor no fija una tolerancia; como la
  marca está firmada, vale la de la sección 4.4.
- Clave del evento: `discord:<id>`, con la misma regla del campo `id` que en `stripe`. Los eventos
  que no traen `id` usan la huella del cuerpo.

## 6. Recibir: procesar una sola vez

### 6.1. El almacén de reservas

Es un puerto con tres operaciones. Todas DEBEN ser atómicas.

- `claim(key, token, now, lease_seconds)` devuelve `claimed`, `in_progress` o `duplicate`.
- `complete(key, token, now, retention_seconds)` devuelve si se aplicó.
- `release(key, token)` devuelve si se aplicó.

Una entrada está **reservada** hasta que vence su plazo, o **completada** hasta que vence su
retención. Una entrada vence cuando `now` es mayor o igual que su vencimiento. Reglas de `claim`:

| Estado de la clave | Resultado | Efecto |
|---|---|---|
| No existe, o existe pero ya venció | `claimed` | Queda reservada por `token` hasta `now + lease_seconds` |
| Reservada y sin vencer | `in_progress` | Ninguno |
| Completada y sin vencer | `duplicate` | Ninguno |

`complete` y `release` sólo se aplican si la entrada guardada es una reserva hecha con el mismo
`token`, aunque su plazo haya vencido. Así, quien se demoró puede terminar si nadie tomó la clave,
y quien perdió su reserva no pisa a quien la tomó después. `complete` deja la entrada completada
hasta `now + retention_seconds`; `release` la borra.

Valores por defecto: `lease_seconds = 300` y `retention_seconds = 604800` (siete días).

### 6.2. El caso de uso

Dado un pedido, un esquema, un almacén y una función que procesa el evento:

1. Si el cuerpo tiene más de `max_body_bytes` bytes, devolver `too_large` y terminar.
2. Verificar con el esquema. Si el resultado no es `ok`, devolverlo y terminar.
3. Determinar la clave del evento.
4. Si hay un validador de payload: interpretar el cuerpo como JSON y pasárselo. Si el cuerpo no
   es JSON o el validador lo rechaza, devolver `unprocessable` y terminar.
5. `claim`. Si devuelve `duplicate` o `in_progress`, devolver ese resultado y terminar.
6. Ejecutar la función que procesa el evento.
7. Si termina bien: `complete` y devolver `ok`.
8. Si falla: `release` y devolver `failed` con el error adjunto.

La función que procesa el evento NO DEBE ejecutarse si el paso 2 no dio `ok`, el paso 4 dio
`unprocessable` o el paso 5 no dio `claimed`.

El validador de payload es opcional. Recibe el cuerpo ya interpretado y lo acepta, devolviendo el
valor con el que trabaja la función que procesa el evento, o lo rechaza.

- El payload se valida después de verificar: un cuerpo sin autenticar no se interpreta.
- Se valida antes de reservar: un payload inválido no escribe en el almacén. No hay nada que
  liberar, y si el emisor reintenta, el reintento vuelve a dar `unprocessable`.
- El cuerpo se interpreta como JSON estricto en UTF-8, con las mismas reglas que el campo `id` de
  la sección 5.2: con una marca de orden de bytes, con `NaN` o `Infinity`, o vacío, no es JSON.
- `unprocessable` trae la clave del evento y el motivo del rechazo, para registrarlo.

`max_body_bytes` es `1048576` por defecto (1 MiB) y DEBE ser un entero mayor que cero. El tamaño
se comprueba antes que cualquier otra cosa, incluidos los secretos: calcular una firma sobre un
cuerpo arbitrariamente grande es trabajo que un pedido sin autenticar no debe poder provocar.

Este límite acota el trabajo de verificar, no la memoria: cuando el caso de uso recibe el pedido,
el cuerpo ya se leyó. El servidor o el framework que lo lee DEBERÍA tener su propio límite, igual
o menor.

### 6.3. Respuesta HTTP sugerida

| Resultado | Estado | Por qué |
|---|---|---|
| `ok` | 200 | Procesado |
| `duplicate` | 200 | Ya se había procesado: el emisor tiene que dejar de reintentar |
| `in_progress` | 409 | Otro proceso lo está procesando: conviene que el emisor reintente |
| `missing`, `ambiguous`, `malformed`, `invalid`, `stale` | 401 | No se pudo comprobar el origen |
| `too_large` | 413 | El cuerpo supera el máximo: reintentar no lo va a arreglar |
| `unprocessable` | 422 | La firma es válida pero el payload no tiene la forma esperada: reintentar no lo va a arreglar |
| `unconfigured` | 500 | Es un problema del receptor: conviene que el emisor reintente |
| `failed` | 500 | Falló el procesamiento y la reserva quedó libre |

El cuerpo de la respuesta NO DEBE decir cuál de las comprobaciones falló.

### 6.4. Observar

Quien integra PUEDE registrar un observador de la recepción. Después de cada pedido, cualquiera
sea el resultado, el observador recibe:

| Dato | Contenido |
|---|---|
| `outcome` | El resultado (secciones 4 y 6.2) |
| `event_key` | La clave del evento, o nulo si el pedido no llegó a verificarse |
| `duration_ms` | Cuánto llevó la recepción completa, incluido el procesamiento |

- El observador NO DEBE recibir el cuerpo, las cabeceras ni ningún secreto.
- El observador no cambia el resultado. Si falla, su error se descarta: una falla al medir no
  puede hacer que un webhook se rechace ni que se procese dos veces.
- Se lo llama una sola vez por pedido, después de completar o liberar la reserva.

Para la emisión no hace falta un puerto aparte: el registro de entregas (sección 8.4) ya recibe
cada intento con su clase, su estado HTTP y su duración.

## 7. Emitir: firmar

Un mensaje tiene `id`, `timestamp` (segundos) y `payload` (bytes).

- El `id` identifica al mensaje, no al intento: se mantiene igual en todos los reintentos.
- El `id` NO DEBE estar vacío ni contener `.`.
- El mensaje se firma con el esquema `standard` y se envía con las cabeceras `webhook-id`,
  `webhook-timestamp` y `webhook-signature`.
- El `timestamp` es el del intento: cada reintento se firma de nuevo con la hora actual.
- Con más de un secreto se envía una firma por secreto, separadas por un espacio y en el orden
  de la lista.
- El cuerpo enviado DEBE ser, byte a byte, el `payload` que se firmó.
- El `payload` NO DEBE tener más de `max_payload_bytes` bytes: `262144` por defecto (256 KiB),
  y DEBE ser un entero mayor que cero. Uno más grande no se firma ni se envía: es un error de
  quien integra, igual que un `id` inválido, y no queda en el registro. El valor por defecto es
  menor que el `max_body_bytes` por defecto de la sección 6.2, así lo que un paquete emite el otro
  lo recibe sin configurar nada.
- Cada intento lleva una cabecera `user-agent` con la forma
  `omniwebhook/<versión del paquete> (<lenguaje>)`, donde el lenguaje es `typescript` o `python`.
  Por ejemplo, `omniwebhook/0.4.0 (python)`. Sirve para que quien recibe pueda reconocer el
  tráfico; no es una prueba de origen, que para eso está la firma.
- Las cabeceras que agrega quien integra NO DEBEN reemplazar ni duplicar las de la firma, la del
  tipo de contenido ni `user-agent`. Los nombres se comparan sin distinguir mayúsculas.

## 8. Emitir: entregar

### 8.1. Política de URLs de destino

Antes de cada intento se valida la URL y las direcciones a las que resuelve.

- El esquema DEBE ser `https`. `http` sólo se acepta si la configuración lo permite expresamente.
- La URL NO DEBE traer usuario ni contraseña.
- Si el nombre es una dirección IP literal, se evalúa esa dirección y no se resuelve nada.
- Si no, el nombre se resuelve a direcciones IP. Si alguna dirección está bloqueada, el intento se
  rechaza. Si no resuelve a ninguna, también.
- Si la resolución falla, en vez de responder sin direcciones, el intento cuenta como un error de
  red (sección 8.2): puede ser pasajero.
- La conexión DEBE hacerse a una de las direcciones validadas, no a una resolución nueva.
- Las redirecciones no se siguen.

Rangos bloqueados:

| IPv4 | IPv6 |
|---|---|
| `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8` | `::/128`, `::1/128` |
| `169.254.0.0/16`, `172.16.0.0/12`, `192.0.0.0/24`, `192.0.2.0/24` | `64:ff9b::/96`, `100::/64` |
| `192.168.0.0/16`, `198.18.0.0/15`, `198.51.100.0/24`, `203.0.113.0/24` | `2001:db8::/32`, `fc00::/7` |
| `224.0.0.0/4`, `240.0.0.0/4` | `fe80::/10`, `ff00::/8` |

Una dirección IPv6 que envuelve una IPv4 (`::ffff:0:0/96`) se evalúa por la IPv4 que contiene.

#### Redes permitidas

La configuración PUEDE traer una lista de redes permitidas, vacía por defecto. Sirve para entregar
a servicios de una red propia, como los de una instalación en la misma máquina o la misma red
local. Una dirección está bloqueada si no es una dirección IP, o si cae en un rango bloqueado y no
cae en ninguna red permitida.

Nunca se permiten, aunque una red de la lista las incluya, las direcciones de los servicios de
metadatos de las nubes:

| IPv4 | IPv6 |
|---|---|
| `169.254.0.0/16`, `100.100.100.200/32` | `fd00:ec2::254/128` |

Una IPv6 que envuelve una IPv4 se evalúa por la IPv4 también acá: se compara con las redes IPv4
de la lista.

Cada red se escribe `dirección/prefijo`:

- `dirección` es una IPv4 o una IPv6 con la forma de la gramática de abajo, sin corchetes.
- `prefijo` es un número decimal sin ceros a la izquierda, de 0 a 32 para IPv4 y de 0 a 128 para
  IPv6.
- Los bits de la dirección que quedan fuera del prefijo DEBEN ser cero: `10.0.0.0/8` sí,
  `10.0.0.1/8` no.
- Una red IPv6 dentro de `::ffff:0:0/96` no se acepta: esas direcciones se evalúan por su IPv4.

Una red que no cumple esto es un error de configuración y se rechaza al armar el emisor, no en
cada intento. Permitir una red que no está bloqueada no cambia nada.

#### Forma de la URL

La URL no se le entrega al analizador de URLs de la plataforma hasta comprobar que tiene esta forma,
porque los analizadores no coinciden entre sí ante una URL rara y esa diferencia es justo lo que
aprovecha quien quiere llegar a una dirección interna.

```
url       = esquema "://" [ usuario "@" ] host [ ":" puerto ] [ resto ]
esquema   = "http" / "https"                    ; sin distinguir mayúsculas
host      = "[" IPv6 "]" / IPv4 / nombre
nombre    = etiqueta *( "." etiqueta ) [ "." ]  ; hasta 253 caracteres
etiqueta  = 1*63( letra ASCII / dígito / "-" / "_" )
puerto    = 1*5 dígito                          ; hasta 65535
resto     = ( "/" / "?" / "#" ) cualquier cosa
```

- La URL NO DEBE contener la barra invertida, ni caracteres de U+0000 a U+0020, ni U+007F.
- `usuario` es todo lo que hay antes del último `@` de la parte que va entre `://` y el `resto`.
- `IPv4` son cuatro números decimales de 0 a 255 sin ceros a la izquierda; `IPv6`, la notación
  habitual, sin identificador de zona. Son las únicas formas que cuentan como dirección literal.
- Un `nombre` cuya última etiqueta es un número (sólo dígitos, o `0x` seguido de dígitos
  hexadecimales) no se acepta: hay analizadores que lo leen como una dirección.
- Un nombre con caracteres fuera de ASCII va en su forma ASCII (`xn--…`).
- El host se usa en minúsculas.

Se revisa en este orden:

1. Sin un esquema al principio (`^[A-Za-z][A-Za-z0-9+.-]*:`), o con un carácter prohibido:
   `invalid_url`.
2. Con un esquema que no es `https`, ni `http` con el permiso expreso: `scheme`.
3. Si lo que sigue no tiene la forma de arriba: `invalid_url`.
4. Si trae `usuario`, aunque esté vacío: `credentials`.

El resultado de la política es `allowed` o el primer motivo de rechazo, en este orden:

| Motivo | Cuándo |
|---|---|
| `invalid_url` | No tiene la forma de una URL de destino |
| `scheme` | El esquema no es `https`, ni `http` con el permiso expreso |
| `credentials` | Trae usuario o contraseña |
| `unresolved` | El nombre no resolvió a ninguna dirección |
| `blocked_address` | Alguna dirección está bloqueada: en un rango bloqueado y fuera de las redes permitidas, o no es una dirección IP |

La URL de destino NO DEBE aparecer en un error ni en un log.

### 8.2. Clasificación de la respuesta

| Lo que pasó | Clase | Qué sigue |
|---|---|---|
| Estado 2xx | `delivered` | Nada más |
| Estado 410 | `gone` | No se reintenta y el destino se deshabilita |
| Estado 408, 409, 425, 429 o 5xx | `retryable` | Se reintenta |
| Error de red o tiempo de espera agotado | `retryable` | Se reintenta |
| Cualquier otro estado, incluidos los 3xx | `rejected` | No se reintenta |
| La política de URLs rechazó el intento | `blocked` | No se reintenta |

El tiempo de espera es el plazo del intento completo, desde que se empieza a conectar hasta tener
el estado de la respuesta. NO DEBE ser un plazo por operación de red: un servidor que manda la
respuesta de a un byte no puede estirar el intento. Por defecto son 20 segundos.

El cuerpo de la respuesta NO DEBE leerse. Para clasificar el intento alcanzan el estado y la
cabecera `retry-after`: con eso la conexión se cierra, y un destino no puede hacerle gastar
memoria ni tiempo a quien emite respondiendo con un cuerpo enorme o que no termina.

### 8.3. Reintentos

La política de reintentos es un dato: una lista de esperas en segundos entre un intento y el
siguiente. Por defecto:

```
[5, 300, 1800, 7200, 18000, 36000, 50400, 72000, 86400]
```

Con esa lista hay diez intentos: el primero es inmediato.

Después del intento número `n` (el primero es el 1) con clase `retryable`:

- Si `n` es mayor que el largo de la lista, no hay más intentos: la entrega queda `exhausted`.
- Si no, la espera base es el elemento `n` de la lista (contando desde 1).
- Si la respuesta trajo `retry-after`, la espera es el mayor entre la base y ese valor.
  `retry-after` puede ser un entero de segundos (`^[0-9]+$`) o una fecha HTTP con la forma
  `Sun, 06 Nov 1994 08:49:37 GMT`, que se convierte en `fecha - ahora`. Uno que no se puede
  interpretar o que da un valor negativo se ignora.
- La espera nunca supera `max_delay_seconds` (por defecto `86400`).
- A la espera se le suma una variación: `piso(espera × jitter_ratio × r)`, donde `r` es un número
  en `[0, 1)` que llega inyectado y `jitter_ratio` es `0.1` por defecto. La variación se aplica
  después del tope.
- El próximo intento es en `ahora + espera`.

### 8.4. El registro de entregas

Es un puerto. Por cada intento guarda: el `id` del mensaje, el destino, el número de intento, la
clase del resultado, el estado HTTP si lo hubo, la duración y cuándo corresponde el siguiente.

El estado de una entrega es `pending`, `delivered`, `rejected`, `blocked`, `gone` o `exhausted`.

Después de cada intento, el estado sale de la clase del resultado: `delivered`, `rejected`,
`blocked` y `gone` pasan tal cual; `retryable` queda `pending` si hay un próximo intento y
`exhausted` si no.

Reenviar a mano una entrega es enviarla de nuevo desde el intento 1 con el mismo `id` del mensaje,
para que el receptor pueda reconocerla.

#### La tabla de PostgreSQL

Un registro sobre PostgreSQL DEBE usar esta tabla, para que lo que registra un paquete lo lea el
otro. El nombre por defecto es `omniwebhook_attempts`:

| Columna | Tipo | Contenido |
|---|---|---|
| `id` | `bigint`, identidad | El orden en que se registró |
| `message_id` | `text` | El `id` del mensaje |
| `endpoint_id` | `text` | El identificador del destino, nunca su URL |
| `attempt` | `integer` | El número de intento |
| `at` | `bigint` | Cuándo empezó el intento, en segundos |
| `delivery_class` | `text` | La clase del resultado (sección 8.2) |
| `state` | `text` | El estado de la entrega después del intento |
| `status` | `integer`, nulo | El estado HTTP, si hubo respuesta |
| `problem` | `text`, nulo | El motivo de la política de URLs, si rechazó el intento |
| `duration_ms` | `bigint` | Cuánto duró el intento |
| `next_at` | `bigint`, nulo | Cuándo corresponde el próximo intento |

Un reenvío repite números de intento, así que la clave es `id` y no `(message_id, endpoint_id,
attempt)`. Hay un índice por `(message_id, endpoint_id)` y otro por `(endpoint_id, at)`.

Leer los intentos de un mensaje hacia un destino devuelve las filas en el orden de `id`.

El paquete calcula cuándo corresponde el próximo intento pero no lo ejecuta. Quien integra puede
programarlo con lo que ya use, o apoyarse en la bandeja de salida.

### 8.5. La bandeja de salida

Es un puerto opcional: guarda las entregas pendientes para que no se pierdan si el proceso se
cae, y las reparte sin que dos procesos entreguen la misma. No es una cola con planificador:
alguien tiene que pedirle la próxima tanda.

Una entrada es un mensaje para un destino. Guarda el `id` del mensaje, el identificador del
destino (nunca su URL), el payload en bytes, el número del próximo intento, desde cuándo está
disponible y su estado. El par `(id del mensaje, destino)` es único.

El estado es `pending` o uno final: `delivered`, `rejected`, `blocked`, `gone`, `exhausted`
(los de la sección 8.4) o `cancelled`, para una entrega que se descartó sin intentarla.

Tiene cuatro operaciones. Todas DEBEN ser atómicas.

- `enqueue(message_id, endpoint_id, payload, now)` devuelve si se encoló. Crea la entrada como
  `pending`, con el intento `1` y disponible desde `now`. Si el par ya existe, en cualquier
  estado, no cambia nada y devuelve falso.
- `claim(token, now, limit, lease_seconds)` toma hasta `limit` entradas y las devuelve con su
  payload y su número de intento. Se pueden tomar las `pending` que estén disponibles (`now`
  mayor o igual que su momento) y que no estén tomadas, o cuya toma haya vencido (`now` mayor o
  igual que su vencimiento). Salen ordenadas por el momento desde el que están disponibles y, a
  igual momento, por el orden en que se encolaron. Cada una queda tomada por `token` hasta
  `now + lease_seconds`.
- `settle(message_id, endpoint_id, token, state, next_at)` devuelve si se aplicó. Sólo se aplica
  si la entrada está `pending` y la tomó ese mismo `token`, aunque el plazo haya vencido. Con
  `state = pending`, el número de intento sube en uno, la entrada queda disponible desde
  `next_at` y se libera la toma. Con un estado final, queda en ese estado.

- `requeue(endpoint_id, from, to, now)` devuelve cuántas entradas reenvió. Alcanza a las de ese
  destino que se cerraron sin entregar (cualquier estado final menos `delivered`) y cuyo
  momento de disponibilidad está entre `from` y `to`, los dos incluidos. Cada una vuelve a
  `pending`, con el intento `1` y disponible desde `now`. El `id` del mensaje no cambia: es el
  reenvío de la sección 8.4.

Las reglas de la toma son las de la reserva de la sección 6.1: quien se demoró puede cerrar si
nadie tomó la entrada, y quien perdió su toma no pisa a quien la tomó después.

Consecuencias que quien integra tiene que conocer:

- **Al menos una vez.** Si el proceso se cae después de entregar y antes de `settle`, la entrada
  vuelve a salir al vencer la toma, con el mismo `id` de mensaje. Para eso el receptor reserva el
  evento (sección 6).
- **Sin orden entre mensajes.** Dos mensajes para un mismo destino pueden llegar en cualquier
  orden: un reintento demora a uno y no al otro.
- `lease_seconds` DEBE ser mayor que lo que puede tardar en despacharse una tanda entera.

#### Despachar una tanda

Dados una bandeja, un directorio de destinos y quien hace el intento (sección 8):

1. `claim` con un token nuevo.
2. Por cada entrada, preguntarle al directorio por el destino. Si no existe o está deshabilitado,
   `settle` con `cancelled`, sin intentar ni registrar nada.
3. Si existe, hacer un intento con el número de intento de la entrada.
4. `settle` con el estado en que quedó la entrega; si es `pending`, con su `next_at`.

Si el intento no llega a hacerse por un error de quien integra (sección 7), la entrada no se
cierra: vuelve a salir al vencer la toma, y el error se informa en el resultado de la tanda.

#### La salud de un destino

La salud de un destino se calcula del registro de entregas (sección 8.4); no es un dato que se
guarde aparte.

El **resumen de fallos** de un destino desde un momento `since` mira sus intentos con `at` mayor
o igual que `since`, en el orden en que se registraron, y de ellos sólo los posteriores al
último con clase `delivered`:

| Dato | Contenido |
|---|---|
| `failures` | Cuántos son |
| `failing_since` | El menor `at` entre ellos; nulo si no hay ninguno |
| `gone` | Si alguno tiene clase `gone` |

`since` es `0` para un destino que nunca se deshabilitó, y el momento en que se lo rehabilitó
para uno que sí: así lo que pasó antes no lo vuelve a deshabilitar.

Con ese resumen, la hora actual y dos parámetros, `window_seconds` (por defecto `432000`, cinco
días) y `min_failures` (por defecto `5`), los dos enteros mayores que cero:

| Condición, en este orden | Estado | Motivo |
|---|---|---|
| `gone` | `disabled` | `gone` |
| `failures >= min_failures` y `ahora - failing_since >= window_seconds` | `disabled` | `failing` |
| `failures > 0` | `failing` | ninguno |
| Ninguna | `healthy` | ninguno |

Hacen falta las dos cosas, cantidad y tiempo: muchos fallos en un rato son una caída que se
recupera, y un fallo aislado hace una semana no dice nada.

Al despachar una tanda, después de un intento que no se entregó, se calcula la salud del destino.
Si da `disabled`, el resultado de la tanda lo informa. El paquete no deshabilita nada por su
cuenta: guardar ese estado, dejar de resolver el destino y avisarle a su dueño es de quien
integra. Mientras el directorio lo siga resolviendo, se le sigue entregando.

#### La tabla de PostgreSQL

Una bandeja sobre PostgreSQL DEBE usar esta tabla, para que lo que encola un paquete lo despache
el otro. El nombre por defecto es `omniwebhook_outbox`:

| Columna | Tipo | Contenido |
|---|---|---|
| `seq` | `bigint`, identidad | El orden en que se encoló |
| `message_id` | `text` | El `id` del mensaje |
| `endpoint_id` | `text` | El identificador del destino, nunca su URL |
| `payload` | `bytea` | El cuerpo, byte a byte como se va a enviar |
| `attempt` | `integer` | El número del próximo intento |
| `available_at` | `bigint` | Desde cuándo se puede tomar, en segundos |
| `state` | `text` | El estado de la entrada |
| `token` | `text`, nulo | Quién la tiene tomada |
| `lease_expires_at` | `bigint`, nulo | Hasta cuándo vale la toma |

La clave es `(message_id, endpoint_id)`. Hay un índice por `(state, available_at)`.

## 9. Vectores de conformidad

Cada archivo de `vectors/` tiene la forma que describe
[`schemas/vector.schema.json`](schemas/vector.schema.json): `spec`, `id`, `kind` y `cases`. El
campo `kind` dice qué se está probando y qué campos trae cada caso.

Los vectores los genera `tools/gen_vectors.py`, que es una implementación aparte de este documento
y no importa ninguno de los paquetes. Todos los secretos que aparecen en los vectores son
sintéticos.
