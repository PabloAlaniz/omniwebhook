# omniwebhook

Webhooks firmados que se emiten y se reciben igual en cualquier stack.

> **En construcción.** Todavía no hay una versión publicada. La [especificación](spec/SPEC.md) y
> las [decisiones de arquitectura](docs/adr/README.md) se escriben antes que el código.

Casi todo producto termina recibiendo webhooks de un proveedor de pagos y emitiendo los suyos. Y
casi siempre se escribe de nuevo: una verificación de firma por proveedor, una tabla para no
procesar dos veces, un reintento a mano. `omniwebhook` separa las reglas de todo lo demás:

- **Las mismas reglas para recibir.** Verificar la firma, rechazar lo viejo, rechazar lo ambiguo y
  procesar cada evento una sola vez, con un resultado tipado en vez de excepciones.
- **Un formato abierto para emitir.** Lo que sale se firma con
  [Standard Webhooks](https://www.standardwebhooks.com/), con reintentos definidos como datos.
- **Cualquier proveedor, cualquier base, cualquier cliente HTTP.** El núcleo no los conoce: son
  puertos, y cada uno se resuelve con un adaptador.
- **El mismo comportamiento en cada lenguaje.** Hay una especificación y vectores de conformidad
  compartidos; el paquete de TypeScript y el de Python corren los mismos casos.

## Las dos reglas que no se negocian

1. **Nada se procesa sin verificar.** Si falta el secreto, se rechaza: no hay un modo que saltee
   la verificación. Comprobar que el aviso es reciente es parte de verificar.
2. **Cada evento produce efecto una sola vez.** El evento se reserva antes de procesarlo. Si el
   procesamiento falla, la reserva se libera para que el reintento del emisor funcione.

## Estructura del repositorio

| Carpeta | Qué hay |
|---|---|
| [`spec/`](spec/) | La especificación y los vectores de conformidad |
| [`ts/`](ts/) | El paquete de TypeScript (npm) |
| [`python/`](python/) | El paquete de Python (PyPI) |
| [`tools/`](tools/) | El generador de vectores, independiente de los dos paquetes |
| [`docs/adr/`](docs/adr/) | Las decisiones de arquitectura |

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). Para reportar un problema de seguridad, ver
[SECURITY.md](SECURITY.md).

## Licencia

[MIT](LICENSE)
