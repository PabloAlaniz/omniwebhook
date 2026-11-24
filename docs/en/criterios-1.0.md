# Criteria for 1.0

> **Translation.** This is a translation of the [Spanish original](../criterios-1.0.md). If the two disagree, the Spanish text wins.

1.0 is a promise: from then on, a breaking change only comes in a major version
(see [Compatibility](compatibilidad.md)). This page says what has to be true before
making it, and what is expressly left out so that it does not delay it.

There is no date. It is published when everything under "Has to be there" is ticked.

## Has to be there

### Open decisions, closed

- [ ] **Invalid `xn--` labels in the destination URL.** Today they pass the grammar and one of the
  platforms rejects them when connecting. Decide in the specification whether they are `invalid_url`.
- [ ] **Signature over the URL plus the parameters.** Decide whether it comes in. If it does, the incoming request
  starts carrying the full URL, and that is a change to the model that is best made before
  freezing.
- [ ] **Concurrency cap per endpoint in the outbox.** Decide whether it comes in or is left for later.
- [ ] **What to do with a delivery that always fails before the attempt.** Today it goes out again every
  time its claim expires. Decide whether the outbox discards it after a certain number of times.

### The specification

- [ ] `spec/VERSION` becomes `1`, and with that the outcomes, their HTTP statuses, the
  schemes, the shared tables and the telemetry names are fixed.
- [ ] Every rule of the specification has at least one vector that demonstrates it.

### What has not yet been tested against the real service

- [ ] The DynamoDB and Workers KV clients, which today run against in-memory doubles.
- [ ] The smoke test inside a Worker, in addition to Node, Deno and Bun.
- [ ] The new workflows (static analysis, security assessment, nightly fuzzing,
  dependency review, dependency inventory) running on `main`.

### Confidence

- [ ] Thirty consecutive nights of differential fuzzing without differences between the packages.
- [ ] A security review by someone who did not write the code, at least of
  signature verification, the destination URL policy and the outbox.
- [ ] A real use of each half: a service that receives and one that sends, in production, for
  a month, with their problems written up in issues.

### The API

- [ ] Review of what each public entry point exports: whatever does not have to be public goes.
- [ ] The names of the options match between the two packages, except for the convention of each
  language.
- [ ] Nothing remains marked as deprecated.

### The documentation

- [x] In English, in addition to Spanish: the README, the guides and the specification.
- [ ] The specification in English, read in full against the original by a second person.
- [ ] The translations of the README into Simplified Chinese and Brazilian Portuguese, reviewed by
  someone who speaks the language.
- [x] Every example in the documentation goes through the checker, in both languages.
- [ ] A migration guide from the last 0.x.

## Left out of 1.0

None of this blocks it. It can be added later without breaking anyone.

- Outbox on SQLite, Redis or key-value.
- Dated rotation of secrets.
- Event catalog in OpenAPI.
- Signing with a key that lives in a key management service.
- Documentation site.
- A third language.

## Never

- A service to deploy, a scheduler or a queue of its own.
- A mode that skips verification.
