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

Eso ya está configurado. Queda anotado por si hay que rehacerlo:

| Dónde | Qué |
|---|---|
| GitHub, *Settings → Actions → General* | Permitir que GitHub Actions cree pull requests; sin eso, release-please no puede abrir el de la versión |
| GitHub, *Settings → Environments* | Los entornos `npm` y `pypi`, sin aprobación manual |
| PyPI, *Publishing* | El publicador de confianza del proyecto `omniwebhook`: este repositorio, workflow `release.yml`, entorno `pypi` |
| npm, *omniwebhook → Settings → Trusted Publisher* | El publicador de confianza: este repositorio, workflow `release.yml`, entorno `npm`, con **Allow npm publish** marcado |

Detalles de npm que no son obvios:

- El publicador de confianza sólo se puede configurar sobre un paquete que ya existe. Por eso la
  0.1.0 se publicó a mano desde `ts/` y recién la 0.1.1 salió del workflow.
- Si no se marca **Allow npm publish**, el publicador sólo puede hacer `npm stage publish`: la
  versión queda en espera hasta aprobarla a mano con 2FA, y el `npm publish` del workflow falla.
- Un publicador nuevo queda *Pending validation* y vence si el workflow no publica en unos dos días.
  Para validarlo hace falta una versión nueva; volver a correr el job de una versión ya publicada
  no sirve.

La primera versión arranca en 0.1.0 por `initial-version` en `release-please-config.json`; sin eso,
release-please propone 1.0.0.

## Si algo sale mal

Una versión publicada no se puede reemplazar. Si un paquete se publicó y el otro no, se corrige la
causa y se vuelve a correr sólo el job que falló. Si la versión publicada tiene un error, se
publica una nueva; no se borra la anterior.
