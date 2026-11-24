# 0009. Una bandeja de salida y el despacho de una tanda, sin planificador

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

`SendWebhook` hace un intento y dice cuándo corresponde el siguiente. Guardar el mensaje,
acordarse de reintentarlo y no perderlo si el proceso se cae quedaba del lado de quien integra.
El registro de entregas no alcanza para eso: guarda el historial de los intentos, pero no el
payload, ni se le puede pedir «lo pendiente que ya venció».

Eso es lo más difícil de emitir webhooks, y es lo que cada proyecto termina escribiendo de
nuevo. Además, deshabilitar un destino caído, reenviar por rango de tiempo y limitar la
concurrencia por destino necesitan un lugar donde vivan las entregas.

Lo opuesto, un despachador con su propio bucle, es otra cosa: una cola con planificador, con su
ritmo, su apagado ordenado y sus reintentos de infraestructura. El paquete es una librería.

## Decisión

1. Hay un puerto `Outbox` con tres operaciones: encolar, tomar lo vencido y cerrar. Es opcional:
   `SendWebhook` no cambia, y quien ya tiene su cola lo sigue usando igual.
2. La toma es una reserva, con las reglas que ya existen para recibir: un plazo y un token.
   Quien se demoró puede cerrar si nadie tomó la entrada; quien perdió su toma no pisa a quien la
   tomó después.
3. `DispatchDue` despacha una tanda y termina. No tiene bucle ni planificador: quien integra lo
   llama desde un cron, una cola o un bucle propio.
4. La bandeja guarda el identificador del destino, nunca su URL ni su secreto, igual que el
   registro. La URL la da un puerto, `EndpointDirectory`, que implementa quien integra; un
   destino que no existe o está deshabilitado cancela la entrega.
5. El despacho recibe «quien hace el intento» como puerto. Con un solo secreto para todos los
   destinos, es `SendWebhook`; con uno por destino, es algo que elige cuál usar.
6. Encolar acepta la transacción de quien integra: el adaptador recibe el cliente SQL, y puede
   ser el de una transacción abierta.
7. Si un intento no llega a hacerse por un error de quien integra, la entrada no se cierra: se
   informa en el resultado de la tanda y vuelve a salir al vencer la toma.
8. Adaptadores: memoria y PostgreSQL. La tabla está en la especificación y es la misma en los
   dos paquetes.

## Consecuencias

- La entrega es al menos una vez: si el proceso se cae entre entregar y cerrar, el mensaje sale
  de nuevo con el mismo `id`. El receptor lo reconoce porque reserva el evento.
- No hay orden entre los mensajes de un mismo destino.
- Una entrada que siempre falla antes del intento vuelve a salir cada vez que vence su toma.
  Queda visible en el resultado de cada tanda; decidir cuándo descartarla es de quien integra.
- La toma tiene que durar más que una tanda entera: el límite por el tiempo de espera de un
  intento. Con los valores por defecto, diez entregas de veinte segundos entran en los
  trescientos de la toma.
- SQLite, Redis y los almacenes clave-valor no tienen bandeja todavía.
