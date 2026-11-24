# Cómo contribuir

## Antes de escribir código

1. **La especificación manda.** Un cambio de comportamiento empieza en [`spec/SPEC.md`](spec/SPEC.md)
   y en los vectores, y recién después llega a los paquetes.
2. **Primero el test.** Cada regla entra con el vector o el test que la demuestra.
3. **Las dependencias apuntan hacia adentro.** Leé
   [la decisión 0001](docs/adr/0001-arquitectura-en-capas.md) antes de agregar un módulo.
4. **Una decisión de diseño nueva es un archivo nuevo** en [`docs/adr/`](docs/adr/).

## Preparar el entorno

Hace falta Node 22 o superior con pnpm, y Python 3.11 o superior con [uv](https://docs.astral.sh/uv/).

```bash
pnpm install
cd python && uv sync
```

## Qué correr antes de abrir un pull request

```bash
# En la raíz: vectores, estilo, tipos, arquitectura, tests y empaquetado de TypeScript.
pnpm check

# En python/: lo mismo para Python.
uv run ruff format --check . ../tools ../examples
uv run ruff check . ../tools ../examples
uv run mypy
uv run lint-imports
uv run pytest
```

La integración continua corre exactamente esto.

Los almacenes que hablan con un servicio se prueban aparte, contra el servicio de verdad:

```bash
docker run -d --rm --name omniwebhook-pg -e POSTGRES_PASSWORD=prueba -p 127.0.0.1:55432:5432 postgres:17-alpine
docker run -d --rm --name omniwebhook-redis -p 127.0.0.1:56379:6379 redis:8-alpine
docker run -d --rm --name omniwebhook-firestore -p 127.0.0.1:58080:8080 \
  gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators \
  gcloud emulators firestore start --host-port=0.0.0.0:8080

export OMNIWEBHOOK_PG_URL=postgres://postgres:prueba@127.0.0.1:55432/postgres
export OMNIWEBHOOK_REDIS_URL=redis://127.0.0.1:56379
export OMNIWEBHOOK_FIRESTORE_EMULATOR=127.0.0.1:58080

pnpm test:integration                                # en la raíz: TypeScript
cd python && uv run pytest -m integration --no-cov   # Python
```

## Pruebas basadas en propiedades

Lo que interpreta entrada ajena (cabeceras, URLs, direcciones, `retry-after`) tiene además pruebas
que generan entrada al azar y comprueban que nunca lanza y que el resultado es siempre uno de los
definidos. Corren con el resto de los tests. Si una falla, imprime el caso mínimo que la provoca:
ese caso se agrega como vector antes de corregir.

## Otros entornos de ejecución

`pnpm test:runtime` compila el paquete y corre `ts/test/runtime/smoke.mjs`, un ciclo completo que
sólo usa APIs web. La integración continua corre el mismo archivo en Deno y en Bun.

## Interoperabilidad

`tools/interop.py` levanta un agente por paquete y les manda los mismos pedidos: los vectores y
miles de variaciones al azar. Comprueba que lo que firma uno lo verifica el otro, que los dos
responden lo mismo ante cualquier pedido y, con `OMNIWEBHOOK_PG_URL`, que comparten una misma tabla
de reservas.

```bash
pnpm test:interop                                   # compila TypeScript y corre la prueba
python3 tools/interop.py --seed 7 --rounds 400      # otra semilla, más variaciones
```

Si aparece una diferencia, primero se decide en la especificación cuál es la respuesta correcta, se
agrega el vector y recién después se corrigen los paquetes.

## Ejemplos de la documentación

Los bloques de código de los README y de las guías se revisan con el comprobador de tipos de cada
lenguaje, para que un ejemplo no quede usando una API que ya cambió:

```bash
pnpm check:docs
```

## Ejemplos ejecutables

Los receptores de [`examples/`](examples/) también se prueban: el comprobador levanta cada uno y le
manda un evento firmado, el mismo evento repetido y uno con otro secreto.

```bash
pnpm check:examples
```

## Traducciones

El español es el original. Hay traducciones de:

- **El README**, al inglés, al chino simplificado y al portugués de Brasil (`README.en.md`,
  `README.zh-CN.md`, `README.pt-BR.md`).
- **Todo lo demás**, al inglés: las guías, las decisiones de arquitectura, la hoja de ruta y los
  criterios en `docs/en/`, con los mismos nombres de archivo que los originales; la
  especificación en `spec/SPEC.en.md`; y este archivo, el de seguridad, el código de conducta y
  los README de los paquetes y de los ejemplos, con el sufijo `.en.md` al lado del original.

Un cambio en un original tiene que llegar a sus traducciones en el mismo pull request. No hace
falta acordarse: la integración continua falla si una traducción deja de tener los mismos
títulos, las mismas filas de tabla o los mismos bloques de código que su original.

```bash
pnpm check:translations
```

Los bloques de código se copian tal cual; en las guías sólo se traducen los comentarios, y en la
especificación ni eso. Los ejemplos de las traducciones pasan también por `pnpm check:docs`.

## Vectores de conformidad

Los archivos de `spec/vectors/` los genera `tools/gen_vectors.py`; no se editan a mano.

```bash
python3 tools/gen_vectors.py           # regenera
python3 tools/gen_vectors.py --check   # verifica que el repo esté en sincronía
```

El generador es una implementación aparte de la especificación y no importa ninguno de los
paquetes. Los secretos que usa son sintéticos.

## Agregar un esquema de firma

1. Describí el formato en la especificación, citando la documentación pública del emisor.
2. Agregá sus vectores al generador, incluidos los casos de borde.
3. Escribí el adaptador en `adapters/schemes/` de cada paquete. No hace falta tocar el núcleo.

## Mensajes de commit

Se usan [Conventional Commits](https://www.conventionalcommits.org/es/). El CHANGELOG y las
versiones salen de ahí.

## Qué no va en el repositorio

- Secretos reales, ni siquiera vencidos.
- URLs o datos de sistemas reales en tests, vectores o ejemplos.
