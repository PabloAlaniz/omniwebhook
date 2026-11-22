# Cómo se publica una versión

Los dos paquetes llevan siempre la misma versión y se publican juntos.

## El circuito

1. Cada commit en `main` sigue [Conventional Commits](https://www.conventionalcommits.org/es/).
2. El workflow [`release.yml`](../.github/workflows/release.yml) mantiene abierto un pull request
   con la próxima versión y el CHANGELOG, calculados a partir de esos commits.
3. Integrar ese pull request crea el tag y la versión en GitHub.
4. El mismo workflow publica en npm y en PyPI desde ese tag, después de correr los tests.

La versión se escribe en un solo lugar (`.release-please-manifest.json`) y la herramienta la copia a
`ts/package.json`, `python/pyproject.toml` y `python/uv.lock`.

## Publicación de confianza

Ningún token de publicación está guardado en el repositorio. Cada registro comprueba, con una
credencial de corta vida que emite GitHub, que quien publica es este workflow en este repositorio.

Eso se configura una sola vez, antes de la primera versión:

| Dónde | Qué |
|---|---|
| GitHub, *Settings → Environments* | Crear los entornos `npm` y `pypi`. Conviene exigir una aprobación manual |
| PyPI, *Publishing* | Agregar un publicador pendiente para el proyecto `omniwebhook`: este repositorio, workflow `release.yml`, entorno `pypi` |
| npm, en la configuración del paquete | Agregar el publicador de confianza: este repositorio, workflow `release.yml`, entorno `npm` |

En npm el publicador de confianza se configura sobre un paquete que ya existe. Si el registro
sigue pidiéndolo así, la primera versión se publica a mano desde `ts/` y las siguientes salen solas.

## Antes de la primera versión

- Que la integración continua haya corrido completa al menos una vez.
- Que `pnpm check:package` y `uv build` armen los paquetes sin advertencias.
- Que los nombres sigan libres en los dos registros.

## Si algo sale mal

Una versión publicada no se puede reemplazar. Si un paquete se publicó y el otro no, se corrige la
causa y se vuelve a correr sólo el job que falló. Si la versión publicada tiene un error, se
publica una nueva; no se borra la anterior.
