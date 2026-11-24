# 0007. Firma asimétrica: un esquema aparte y una dependencia opcional

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

Todos los esquemas eran HMAC-SHA256: quien verifica calcula la firma que debería haber llegado y
la compara como texto en tiempo constante. El recorrido común (`schemeVerifier`,
`scheme_verifier`) estaba escrito alrededor de eso: cada esquema define la firma esperada.

El formato estándar tiene además una firma asimétrica, `v2a`, con Ed25519. Quien recibe guarda
una clave pública y no puede calcular la firma esperada: sólo puede preguntar si una firma
verifica. La versión anterior, `v1a`, está obsoleta en el formato y no se implementa.

Web Crypto trae Ed25519 en todos los entornos que el paquete de TypeScript soporta. La biblioteca
estándar de Python no.

## Decisión

1. La firma asimétrica es un esquema aparte, `standard-v2a`, y no una opción de `standard`. Se
   configura con otra cosa (claves públicas y el identificador del destino) y un receptor usa una
   u otra. Para aceptar las dos durante una migración alcanza con que el emisor mande las dos
   firmas: cada esquema ignora la que no es suya.
2. El recorrido común deja de asumir que la firma se compara como texto. Recibe una función que
   dice si una firma recibida vale para una clave. Los esquemas HMAC la arman con la firma
   esperada y la comparación en tiempo constante, como antes; el asimétrico, con la verificación
   de Ed25519. El orden de las comprobaciones sigue en un solo lugar.
3. En Python, Ed25519 sale de `cryptography`, como dependencia opcional (`omniwebhook[ed25519]`).
   Se importa recién cuando alguien pide el esquema, igual que la librería de referencia del
   formato. No se escribe una implementación propia: la criptografía de clave pública no es
   lugar para eso.
4. El generador de vectores sí trae una implementación propia de Ed25519, con la biblioteca
   estándar, porque no puede depender de nada. Sólo firma casos de prueba con claves sintéticas,
   y se comprueba contra el par de claves de ejemplo de la especificación del formato.
5. Un error de la plataforma al cargar una clave o al verificar cuenta como «no verifica». Una
   clave de 32 bytes que no es un punto válido de la curva nunca verifica nada; no se la detecta
   al configurar, porque no todas las plataformas la rechazan.

## Consecuencias

- Agregar otro esquema de clave pública ya no toca el recorrido común.
- El paquete principal de Python sigue sin dependencias obligatorias.
- La emisión con firma asimétrica queda para después: necesita guardar una clave privada, y eso
  pide su propia decisión.
- Las ayudas de prueba no arman pedidos `v2a` hasta que exista esa emisión.
