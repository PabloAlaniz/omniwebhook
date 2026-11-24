# 0008. Un almacén sobre cualquier clave-valor, con la garantía a la vista

- Estado: aceptada
- Fecha: 2026-11-24

## Contexto

Hay despliegues sin base relacional ni Redis: un Worker con su almacén clave-valor, una función
con DynamoDB, o el clave-valor propio de cada plataforma. Escribir un almacén de reservas por
cada servicio no escala, y el que no esté en la lista queda afuera.

Estos almacenes no son iguales en lo que importa. Algunos escriben con condición («sólo si
nadie cambió esto»), y con eso se puede cumplir el contrato de la sección 6.1 entero. Otros no,
y además sus lecturas pueden tardar en ver una escritura reciente: ahí, entre leer que la clave
está libre y escribir la reserva, puede colarse otro proceso.

## Decisión

1. Hay un solo almacén, `KeyValueIdempotencyStore`, escrito contra un puerto mínimo: leer,
   escribir con vencimiento y borrar, con una versión que identifica cada escritura. Quien tenga
   un clave-valor que el paquete no trae implementa ese puerto, que son tres métodos.
2. El puerto declara si es `conditional`. Si lo es, cada operación lee y escribe sólo si la
   versión no cambió; si pierde, vuelve a mirar qué dejó el otro. Si no lo es, escribe sin
   comprobar.
3. El almacén dice qué garantía da: `atomic` o `best-effort`. No se esconde la diferencia detrás
   de una interfaz que parezca igual.
4. Con `best-effort`, dos entregas simultáneas del mismo evento pueden procesarse las dos. Lo
   que sí se evita son los duplicados separados en el tiempo: los reintentos del emisor, que son
   el caso común. Quien necesite la garantía completa usa un cliente condicional u otro almacén.
5. El paquete trae tres clientes: uno en memoria, que sirve de referencia; uno para DynamoDB,
   condicional; y, en TypeScript, uno para Workers KV, que no lo es.
6. Ningún cliente importa la librería de su servicio: reciben el objeto que ya tiene quien
   integra y usan sólo los métodos que necesitan.
7. El valor guardado es el mismo JSON en los dos paquetes, así comparten las reservas.

## Consecuencias

- Sumar un almacén clave-valor nuevo es escribir un cliente, no un almacén.
- Como en Redis, una reserva vencida se conserva un tiempo de gracia y después el servicio la
  borra; los almacenes relacionales la conservan sin límite.
- Los clientes de DynamoDB y de Workers KV se prueban contra dobles en memoria que imitan sus
  condiciones, no contra el servicio. Falta sumarlos a los tests de integración.
