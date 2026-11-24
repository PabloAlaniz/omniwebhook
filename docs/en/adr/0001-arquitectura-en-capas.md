# 0001. Layered architecture with inward-pointing dependencies

> **Translation.** This is a translation of the [Spanish original](../../adr/0001-arquitectura-en-capas.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-22

## Context

The package has to work equally well with any webhook provider, any database, any HTTP client and
any framework, and in more than one language. The rules (what is accepted, when to retry, what
counts as a duplicate) do not change with any of those choices; the choices do change over time.

## Decision

Each package is organized in four layers, and dependencies only point inward:

```
entrypoints → adapters → application → domain
```

- **domain**: pure rules. No input/output, no clock, no network and no external packages.
- **application**: the use cases (receive, send, resend) and the ports they need. It depends only
  on the domain.
- **adapters**: implementations of the ports: signature schemes, stores, HTTP transport, name
  resolution.
- **entrypoints**: thin shortcuts for mounting a use case in a framework. They are optional.

Rules that follow:

1. A new signature scheme is a new adapter with its vectors. The core is not touched.
2. The ports are small and separate: whoever only receives does not depend on anything from
   sending.
3. The clock, the identifier generator, the network and name resolution are injected. The core's
   tests do not touch the network or real time.
4. Adapters with heavy dependencies are published as optional entries of the package. The core has
   no runtime dependencies.

The direction of the dependencies is verified in continuous integration, not by convention:
`dependency-cruiser` in TypeScript, `import-linter` and a test of the domain's imports in Python.

## Consequences

- Changing the database, the HTTP client or the signature library means writing another adapter.
- There are more files and more indirection than in a direct implementation. This is accepted: the
  cost is fixed and small, and the benefit grows with every provider and every store that is added.
- The two implementations share a structure, so a rule is looked up in the same place in either of
  the two languages.
