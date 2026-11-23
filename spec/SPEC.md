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

## 5. Esquemas

Todos usan HMAC-SHA256. «Cuerpo» es siempre el cuerpo crudo.

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

### 5.6. `hmac-body`

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

1. Verificar con el esquema. Si el resultado no es `ok`, devolverlo y terminar.
2. Determinar la clave del evento.
3. `claim`. Si devuelve `duplicate` o `in_progress`, devolver ese resultado y terminar.
4. Ejecutar la función que procesa el evento.
5. Si termina bien: `complete` y devolver `ok`.
6. Si falla: `release` y devolver `failed` con el error adjunto.

La función que procesa el evento NO DEBE ejecutarse si el paso 1 no dio `ok` o el paso 3 no dio
`claimed`.

### 6.3. Respuesta HTTP sugerida

| Resultado | Estado | Por qué |
|---|---|---|
| `ok` | 200 | Procesado |
| `duplicate` | 200 | Ya se había procesado: el emisor tiene que dejar de reintentar |
| `in_progress` | 409 | Otro proceso lo está procesando: conviene que el emisor reintente |
| `missing`, `ambiguous`, `malformed`, `invalid`, `stale` | 401 | No se pudo comprobar el origen |
| `unconfigured` | 500 | Es un problema del receptor: conviene que el emisor reintente |
| `failed` | 500 | Falló el procesamiento y la reserva quedó libre |

El cuerpo de la respuesta NO DEBE decir cuál de las comprobaciones falló.

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
- Las cabeceras que agrega quien integra NO DEBEN reemplazar ni duplicar las de la firma ni la del
  tipo de contenido. Los nombres se comparan sin distinguir mayúsculas.

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

El paquete calcula cuándo corresponde el próximo intento pero no lo ejecuta: programarlo es
responsabilidad de quien integra.

## 9. Vectores de conformidad

Cada archivo de `vectors/` tiene la forma que describe
[`schemas/vector.schema.json`](schemas/vector.schema.json): `spec`, `id`, `kind` y `cases`. El
campo `kind` dice qué se está probando y qué campos trae cada caso.

Los vectores los genera `tools/gen_vectors.py`, que es una implementación aparte de este documento
y no importa ninguno de los paquetes. Todos los secretos que aparecen en los vectores son
sintéticos.
