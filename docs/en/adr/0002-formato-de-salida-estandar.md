# 0002. Standard outgoing format, with the reference library behind a port

> **Translation.** This is a translation of the [Spanish original](../../adr/0002-formato-de-salida-estandar.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-22

## Context

When sending a webhook, you have to choose how it is signed. A format of our own forces every
receiver to write its verifier. The open specification [Standard Webhooks](https://www.standardwebhooks.com/)
already defines headers, signed content, secret format and rotation, and verifiers exist in many
languages.

That specification has a reference library (`standardwebhooks`) in the languages of this project.
Using it avoids rewriting cryptography that is already tested; depending on it carelessly ties the
package's public API to a third party.

## Decision

1. What the package sends is signed with the Standard Webhooks format. Each provider's own formats
   exist only as incoming verifiers.
2. Verifying and signing are ports (`Verifier` and `MessageSigner`). The standard format is one
   more adapter of those ports.
3. The reference library is only imported inside that adapter. An architecture rule enforces it.
4. The public API does not expose types or exceptions from the library: the adapter translates
   everything into the domain's typed results.
5. The library is an optional dependency of the adapter, not of the core.
6. The conformance vectors of the standard scheme are the adapter's contract. Any implementation
   that passes them is valid.

## Consequences

- Replacing the library with an implementation of our own is an internal change: same vectors, same
  API, no major version.
- Whoever receives a webhook sent with this package can verify it with any implementation of the
  open specification.
- The adapter has a translation layer to maintain. It is small and is covered by the vectors.
