# Compatibility

> **Translation.** This is a translation of the [Spanish original](../compatibilidad.md). If the two disagree, the Spanish text wins.

What you can rely on as stable, which runtimes are supported and how a change is announced.

## What is public API

- **TypeScript:** what is exported by `omniwebhook`, `omniwebhook/standard`, `omniwebhook/node`,
  `omniwebhook/otel` and `omniwebhook/testing`.
- **Python:** what is in `__all__` of `omniwebhook` and what is exported by the root modules
  (`omniwebhook.standard`, `omniwebhook.postgres`, `omniwebhook.sqlite`, `omniwebhook.redis`, `omniwebhook.key_value`, `omniwebhook.httpx`,
  `omniwebhook.starlette`, `omniwebhook.django`, `omniwebhook.discord`, `omniwebhook.firestore`, `omniwebhook.otel`, `omniwebhook.testing`).
- **The command line:** the `sign`, `verify` and `send` commands, their options and their exit
  codes.
- **The telemetry names:** the metrics and the attributes in the [guide](telemetria.md).
  Changing them breaks dashboards and alerts, so they are treated as a breaking change.
- **The specification:** the outcomes, their suggested HTTP statuses and the tables shared between
  packages.

Everything else is internal, even if it can be imported: the `domain`, `application`,
`adapters` and `entrypoints` folders are reorganized without notice.

## Versions

Both packages carry the same version number and follow
[Semantic Versioning](https://semver.org/).

Before 1.0, the minor version (`0.4` to `0.5`) goes up both with an addition and with a breaking
change, and the patch only with fixes. The [CHANGELOG](../../CHANGELOG.md) marks which
changes are breaking. It is a good idea to pin the dependency to the minor: `~0.4.0` in npm, `~=0.4.0`
in Python.

From 1.0 onwards, a breaking change only goes into a major version.

## Changes to the specification

`spec/VERSION` changes when a request or a delivery that used to give one outcome starts giving another.
Adding a scheme, a new outcome for a case that did not exist before, or an option with a default
value that preserves the behavior does not change it.

The shared tables (reservations and delivery ledger) do not change in a breaking way within
a single version of the specification: two services with different versions of the package
can keep using the same database.

## Supported runtimes

| | Minimum | Tested on |
|---|---|---|
| Node | 22 | 22, 24 and 26 |
| Python | 3.11 | 3.11 to 3.14 |
| Deno | 2 | The latest 2.x, with a smoke test |
| Bun | 1 | The latest, with a smoke test |

A version of Node or of Python is supported for as long as its own project maintains it. When it
stops receiving security fixes, the next minor version of the package may stop
supporting it; never a patch version.

## Deprecations

Before removing or renaming something public:

1. It is marked as deprecated (`@deprecated` in TypeScript, `DeprecationWarning` in Python), with
   what to use in its place.
2. It is noted in the [CHANGELOG](../../CHANGELOG.md).
3. It keeps working for at least one full minor version before 1.0, and until the next
   major version after that.

A security fix may skip these steps. In that case the CHANGELOG says so
explicitly.
