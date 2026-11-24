# 0004. In Python, every piece with input/output has a synchronous and an asynchronous variant

> **Translation.** This is a translation of the [Spanish original](../../adr/0004-variantes-sincronica-y-asincronica.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-22

## Context

Two styles coexist in Python. A service on an asynchronous framework cannot call a store that
blocks, and a synchronous one cannot await a coroutine. Choosing only one leaves out half of those
who could use the package.

## Decision

1. The domain is synchronous: it is pure rules.
2. Verifying and signing too: they are only computation, with no input/output.
3. Every port that does input/output exists twice: `IdempotencyStore` and
   `AsyncIdempotencyStore`, and the same for the transport, name resolution and the ledger.
4. Every use case exists twice: `ReceiveWebhook` and `AsyncReceiveWebhook`, `SendWebhook` and
   `AsyncSendWebhook`. Everything that is not input/output lives in a common base, so each variant
   only repeats the sequence of calls.
5. The same vectors and the same tests run against both variants.

## Consequences

- The integrator chooses the style without losing anything.
- The sequence of each use case is written twice. It is a few lines, and the shared tests keep them
  from drifting apart.
- A new adapter with input/output has to offer both variants, or say which one is missing.
