# Criterios de la 1.0

La 1.0 es una promesa: a partir de ahí, un cambio incompatible sólo entra en una versión mayor
(ver [Compatibilidad](compatibilidad.md)). Esta página dice qué tiene que ser cierto antes de
hacerla, y qué queda expresamente afuera para que no la demore.

No hay fecha. Se publica cuando todo lo de «Tiene que estar» esté tildado.

## Tiene que estar

### Decisiones abiertas, cerradas

- [ ] **Etiquetas `xn--` inválidas en la URL de destino.** Hoy pasan la gramática y una de las
  plataformas las rechaza al conectar. Decidir en la especificación si son `invalid_url`.
- [ ] **Firma sobre la URL más los parámetros.** Decidir si entra. Si entra, el pedido entrante
  pasa a llevar la URL completa, y eso es un cambio del modelo que conviene hacer antes de
  congelar.
- [ ] **Tope de concurrencia por destino en la bandeja.** Decidir si entra o queda para después.
- [ ] **Qué hacer con una entrega que siempre falla antes del intento.** Hoy vuelve a salir cada
  vez que vence su toma. Decidir si la bandeja la descarta después de cierta cantidad.

### La especificación

- [ ] `spec/VERSION` pasa a `1`, y con eso quedan fijos los resultados, sus estados HTTP, los
  esquemas, las tablas compartidas y los nombres de la telemetría.
- [ ] Cada regla de la especificación tiene al menos un vector que la demuestra.

### Lo que todavía no se probó contra el servicio de verdad

- [ ] Los clientes de DynamoDB y de Workers KV, que hoy corren contra dobles en memoria.
- [ ] La prueba de humo dentro de un Worker, además de Node, Deno y Bun.
- [ ] Los workflows nuevos (análisis estático, evaluación de seguridad, fuzzing nocturno,
  revisión de dependencias, inventario de dependencias) corriendo en `main`.

### Confianza

- [ ] Treinta noches seguidas de fuzzing diferencial sin diferencias entre los paquetes.
- [ ] Una revisión de seguridad de alguien que no escribió el código, al menos sobre la
  verificación de firmas, la política de URLs de destino y la bandeja de salida.
- [ ] Un uso real de cada mitad: un servicio que recibe y uno que emite, en producción, durante
  un mes, con sus problemas volcados en issues.

### La API

- [ ] Repaso de lo que exporta cada entrada pública: lo que no tiene que ser público, sale.
- [ ] Los nombres de las opciones coinciden entre los dos paquetes, salvo la convención de cada
  lenguaje.
- [ ] No queda nada marcado como obsoleto.

### La documentación

- [ ] En inglés, además de en español: el README, las guías y la especificación.
- [ ] Cada ejemplo de la documentación pasa por el comprobador, en los dos idiomas.
- [ ] Una guía de migración desde la última 0.x.

## Queda afuera de la 1.0

Nada de esto la bloquea. Se puede sumar después sin romper a nadie.

- Bandeja de salida sobre SQLite, Redis o clave-valor.
- Rotación de secretos con fecha.
- Catálogo de eventos en OpenAPI.
- Firmar con una clave que vive en un servicio de gestión de claves.
- Sitio de documentación.
- Un tercer lenguaje.

## Nunca

- Un servicio para desplegar, un planificador o una cola propios.
- Un modo que saltee la verificación.
