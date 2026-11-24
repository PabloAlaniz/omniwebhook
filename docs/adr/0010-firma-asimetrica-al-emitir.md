# 0010. Firmar con clave privada: el destino entra al mensaje y la clave no sale del emisor

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

La decisión 0007 agregó la verificación de la firma asimétrica del formato estándar, `v2a`, y
dejó la emisión para después. Con secreto compartido, quien recibe puede firmar igual que quien
emite: si se le filtra el secreto, cualquiera puede hacerse pasar por el emisor. Con clave
pública, lo que guarda quien recibe sólo sirve para verificar.

Dos cosas cambian respecto de la firma simétrica. La firma `v2a` incluye el identificador del
destino, y el firmante recibía sólo el mensaje. Y hay una clave privada que cuidar.

## Decisión

1. El mensaje a firmar lleva, además, el identificador del destino. Es el mismo que ya queda en
   el registro y en la bandeja. `SendWebhook` lo completa solo; el firmante simétrico lo ignora.
2. Un identificador vacío o con un punto no se puede firmar con `v2a`. Es un resultado nuevo del
   firmante, `invalid_endpoint`, y no un error en otro lado: el formato usa el punto para separar
   las partes de lo que se firma.
3. La firma asimétrica es otro firmante, `standardKeySigner`, del mismo puerto. No es una opción
   del simétrico: se configura con otra cosa.
4. Para migrar, un firmante combinado junta las firmas de varios en la misma cabecera. Cada
   receptor mira sólo las de su variante, así que se puede pasar de una a la otra sin coordinar
   el momento con cada receptor.
5. Las claves privadas tienen la forma del formato, `whsk_` más la semilla en base64. El paquete
   deriva la pública y genera pares nuevos, pero no las guarda ni las rota: eso es de quien
   integra y de su gestor de secretos.
6. En Python, el par generado no muestra la clave privada al imprimirse.
7. En TypeScript se firma con Web Crypto; en Python, con `cryptography`, el mismo extra opcional
   de la decisión 0007.

## Consecuencias

- Los vectores de firma se comparan byte a byte: Ed25519 es determinista. Tres implementaciones
  independientes coinciden: la del generador de vectores, Web Crypto y `cryptography`. Las
  librerías de referencia del formato que usa el repositorio todavía no traen la variante
  asimétrica, así que no hay una cuarta contra la cual comparar.
- El módulo de pruebas y la línea de comandos ya arman pedidos de los esquemas de clave pública.
- El identificador de destino que se le comunica a quien recibe pasa a ser parte del contrato
  con él: cambiarlo invalida sus verificaciones.
- Firmar con una clave que vive en un servicio de gestión de claves, sin tenerla en memoria, no
  está cubierto. El puerto del firmante lo permite; falta el adaptador.
