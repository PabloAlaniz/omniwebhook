# Compatibilidad

Qué se puede dar por estable, qué entornos se soportan y cómo se avisa un cambio.

## Qué es API pública

- **TypeScript:** lo que exportan `omniwebhook`, `omniwebhook/standard`, `omniwebhook/node` y
  `omniwebhook/testing`.
- **Python:** lo que está en `__all__` de `omniwebhook` y lo que exportan los módulos de la raíz
  (`omniwebhook.standard`, `omniwebhook.postgres`, `omniwebhook.sqlite`, `omniwebhook.redis`, `omniwebhook.key_value`, `omniwebhook.httpx`,
  `omniwebhook.starlette`, `omniwebhook.django`, `omniwebhook.discord`, `omniwebhook.firestore`, `omniwebhook.testing`).
- **La línea de comandos:** los comandos `sign`, `verify` y `send`, sus opciones y sus códigos de
  salida.
- **La especificación:** los resultados, sus estados HTTP sugeridos y las tablas compartidas entre
  paquetes.

Todo lo demás es interno, aunque se pueda importar: las carpetas `domain`, `application`,
`adapters` y `entrypoints` se reorganizan sin aviso.

## Versiones

Los dos paquetes llevan el mismo número de versión y siguen
[Versionado Semántico](https://semver.org/lang/es/).

Antes de la 1.0, la versión menor (`0.4` a `0.5`) sube tanto con un agregado como con un cambio
incompatible, y el parche sólo con correcciones. El [CHANGELOG](../CHANGELOG.md) marca cuáles
cambios son incompatibles. Conviene fijar la dependencia a la menor: `~0.4.0` en npm, `~=0.4.0`
en Python.

A partir de la 1.0, un cambio incompatible sólo entra en una versión mayor.

## Cambios en la especificación

`spec/VERSION` cambia cuando un pedido o una entrega que antes daba un resultado pasa a dar otro.
Agregar un esquema, un resultado nuevo para un caso que antes no existía o una opción con un valor
por defecto que conserva el comportamiento no la cambia.

Las tablas compartidas (reservas y registro de entregas) no cambian de forma incompatible dentro
de una misma versión de la especificación: dos servicios con versiones distintas del paquete
pueden seguir usando la misma base.

## Entornos soportados

| | Mínimo | Se prueba en |
|---|---|---|
| Node | 22 | 22, 24 y 26 |
| Python | 3.11 | 3.11 a 3.14 |
| Deno | 2 | La última 2.x, con una prueba de humo |
| Bun | 1 | La última, con una prueba de humo |

Una versión de Node o de Python se soporta mientras la mantenga su propio proyecto. Cuando deja
de recibir correcciones de seguridad, la siguiente versión menor del paquete puede dejar de
soportarla; nunca una de parche.

## Deprecaciones

Antes de quitar o renombrar algo público:

1. Se marca como obsoleto (`@deprecated` en TypeScript, `DeprecationWarning` en Python), con lo
   que hay que usar en su lugar.
2. Se anota en el [CHANGELOG](../CHANGELOG.md).
3. Sigue funcionando al menos una versión menor completa antes de la 1.0, y hasta la siguiente
   versión mayor después.

Una corrección de seguridad puede saltear estos pasos. En ese caso el CHANGELOG lo dice
expresamente.
