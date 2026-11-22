# 0004. En Python, cada pieza con entrada/salida tiene variante sincrónica y asincrónica

- Estado: aceptada
- Fecha: 2026-11-22

## Contexto

En Python conviven dos estilos. Un servicio sobre un framework asincrónico no puede llamar a un
almacén que bloquea, y uno sincrónico no puede esperar una corrutina. Elegir uno solo deja afuera a
la mitad de quienes podrían usar el paquete.

## Decisión

1. El dominio es sincrónico: son reglas puras.
2. Verificar y firmar también: son sólo cálculo, sin entrada/salida.
3. Cada puerto que hace entrada/salida existe dos veces: `IdempotencyStore` y
   `AsyncIdempotencyStore`, y lo mismo para el transporte, la resolución de nombres y el registro.
4. Cada caso de uso existe dos veces: `ReceiveWebhook` y `AsyncReceiveWebhook`, `SendWebhook` y
   `AsyncSendWebhook`. Todo lo que no es entrada/salida vive en una base común, así que cada
   variante sólo repite la secuencia de llamadas.
5. Los mismos vectores y los mismos tests corren contra las dos variantes.

## Consecuencias

- Quien integra elige el estilo sin perder nada.
- La secuencia de cada caso de uso está escrita dos veces. Son pocas líneas, y los tests compartidos
  impiden que se separen.
- Un adaptador nuevo con entrada/salida tiene que ofrecer las dos variantes, o decir cuál falta.
