# 0008. One store on top of any key-value store, with the guarantee in plain sight

> **Translation.** This is a translation of the [Spanish original](../../adr/0008-almacen-clave-valor.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-24

## Context

There are deployments with no relational database and no Redis: a Worker with its key-value store,
a function with DynamoDB, or each platform's own key-value store. Writing an idempotency store for
every service does not scale, and whichever one is not on the list is left out.

These stores are not the same in what matters. Some write with a condition ("only if nobody
changed this"), and with that the contract of section 6.1 can be met in full. Others do not, and
on top of that their reads can take a while to see a recent write: there, between reading that the
key is free and writing the reservation, another process can slip in.

## Decision

1. There is a single store, `KeyValueIdempotencyStore`, written against a minimal port: read,
   write with expiry and delete, with a version that identifies each write. Whoever has a
   key-value store that the package does not ship implements that port, which is three methods.
2. The port declares whether it is `conditional`. If it is, each operation reads and writes only
   if the version did not change; if it loses, it looks again at what the other one left. If it
   is not, it writes without checking.
3. The store says which guarantee it gives: `atomic` or `best-effort`. The difference is not
   hidden behind an interface that looks the same.
4. With `best-effort`, two simultaneous deliveries of the same event can both be processed. What
   is avoided are duplicates separated in time: the sender's retries, which are the common case.
   Whoever needs the full guarantee uses a conditional client or another store.
5. The package ships three clients: one in memory, which serves as a reference; one for DynamoDB,
   conditional; and, in TypeScript, one for Workers KV, which is not.
6. No client imports its service's library: they receive the object the integrator already has
   and use only the methods they need.
7. The stored value is the same JSON in both packages, so they share reservations.

## Consequences

- Adding a new key-value store means writing a client, not a store.
- As in Redis, an expired reservation is kept for a grace period and then the service deletes it;
  the relational stores keep it with no limit.
- The DynamoDB and Workers KV clients are tested against in-memory doubles that imitate their
  conditions, not against the service. Adding them to the integration tests is still pending.
