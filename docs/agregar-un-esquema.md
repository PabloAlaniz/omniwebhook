# Cómo agregar un esquema de firma

Un esquema es un adaptador: sabe leer el pedido de un emisor, calcular la firma que debería haber
llegado y decir cuál es la clave del evento. El orden de las comprobaciones, la comparación en
tiempo constante, la rotación de secretos y la frescura ya están resueltos y son comunes a todos.

Agregar uno no toca el núcleo. Va en este orden.

## 1. Escribirlo en la especificación

Agregá una sección en [`spec/SPEC.md`](../spec/SPEC.md), junto a los demás esquemas, con la
documentación pública del emisor a la vista. Tiene que responder:

- qué cabeceras o parámetros exige y cuáles son opcionales;
- cómo se interpreta el secreto (texto, base64, con prefijo);
- cuál es exactamente el contenido firmado;
- cómo se codifica la firma (hexadecimal o base64) y si puede venir más de una;
- si lleva marca de tiempo, en qué unidad y con cuántos dígitos como máximo;
- de dónde sale la clave del evento, y qué pasa si ese dato falta.

Si el emisor firma sólo el cuerpo con HMAC-SHA256, probablemente no haga falta un esquema nuevo: el
esquema genérico `hmac-body` ya lo cubre con configuración.

## 2. Agregar los vectores

Los vectores se generan con [`tools/gen_vectors.py`](../tools/gen_vectors.py), que es una
implementación aparte de la especificación. Agregá:

- la verificación del esquema en la función `check`;
- una función `verificar_<esquema>` con los casos.

Como mínimo: una firma válida; cada dato exigido faltando; cada dato repetido; cada forma
inválida; una firma de otro secreto; el cuerpo alterado; la rotación de secretos; y, si lleva marca
de tiempo, el borde exacto de la tolerancia hacia cada lado.

Si el emisor publica un ejemplo con su firma, usalo para comprobar que el generador firma igual.
Todos los secretos de los vectores son sintéticos.

```bash
python3 tools/gen_vectors.py
```

## 3. Escribir el adaptador en cada paquete

Con los vectores generados, los tests de los dos paquetes ya fallan. El adaptador define tres cosas:

| Qué | Para qué |
|---|---|
| La clave del secreto | Convertir el secreto en la clave del HMAC, o decir que no se puede usar |
| La lectura | Sacar del pedido la marca de tiempo, las firmas recibidas y la clave del evento; o devolver `missing`, `ambiguous` o `malformed` |
| La firma esperada | Calcular, para una clave, la firma que debería haber llegado |

En TypeScript es un objeto que se le pasa a `schemeVerifier`
([`ts/src/adapters/schemes/`](../ts/src/adapters/schemes/)); en Python, una clase que se le pasa a
`scheme_verifier` ([`python/src/omniwebhook/adapters/schemes/`](../python/src/omniwebhook/adapters/schemes/)).
El esquema de Stripe es el ejemplo más corto con marca de tiempo; el de GitHub, sin ella.

Reglas que conviene respetar:

- Usar las funciones del dominio para elegir un valor único (`pickSingles`, `pick_singles`) y para
  partir cabeceras con pares (`parsePairs`, `parse_pairs`). Así el orden «primero lo que falta,
  después lo repetido» sale solo.
- La lectura nunca lanza por culpa del pedido: devuelve uno de los tres rechazos.
- La clave del evento se calcula recién cuando la firma resultó válida.
- En hexadecimal, pasar a minúsculas la firma recibida. En base64, dejarla como llegó.

Después, registrar el esquema en los tests de vectores de cada paquete y exportarlo en la entrada
pública.

## 4. Comprobar

```bash
pnpm check                      # TypeScript
cd python && uv run pytest      # Python
pnpm test:interop               # los dos responden lo mismo
```

Sumá el esquema a la lista de `tools/interop.py` para que las variaciones al azar también lo
cubran, y a la tabla de la [guía para recibir](recibir.md).
