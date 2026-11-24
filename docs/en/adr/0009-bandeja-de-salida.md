# 0009. An outbox and the dispatch of a batch, without a scheduler

> **Translation.** This is a translation of the [Spanish original](../../adr/0009-bandeja-de-salida.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-24

## Context

`SendWebhook` makes one attempt and says when the next one is due. Storing the message,
remembering to retry it and not losing it if the process crashes was left to the integrator.
The delivery ledger is not enough for that: it stores the history of the attempts, but not the
payload, nor can it be asked for "what is pending and already due".

That is the hardest part of sending webhooks, and it is what every project ends up writing
again. In addition, disabling an endpoint that is down, resending by time range and limiting
concurrency per endpoint need a place where the deliveries live.

The opposite, a dispatcher with its own loop, is something else: a queue with a scheduler, with
its pace, its orderly shutdown and its infrastructure retries. The package is a library.

## Decision

1. There is an `Outbox` port with three operations: enqueue, claim what is due and settle. It is
   optional: `SendWebhook` does not change, and whoever already has their own queue keeps using it
   the same way.
2. The claim is a reservation, with the rules that already exist for receiving: a deadline and a
   token. Whoever took too long can settle if nobody claimed the entry; whoever lost their claim
   does not overwrite whoever claimed it afterwards.
3. `DispatchDue` dispatches a batch and finishes. It has no loop and no scheduler: the integrator
   calls it from a cron, a queue or a loop of their own.
4. The outbox stores the endpoint identifier, never its URL or its secret, just like the ledger.
   The URL is given by a port, `EndpointDirectory`, which the integrator implements; an endpoint
   that does not exist or is disabled cancels the delivery.
5. The dispatch receives "whoever makes the attempt" as a port. With a single secret for all the
   endpoints, it is `SendWebhook`; with one per endpoint, it is something that chooses which one
   to use.
6. Enqueuing accepts the integrator's transaction: the adapter receives the SQL client, and it can
   be that of an open transaction.
7. If an attempt does not get to be made because of an error on the integrator's side, the entry
   is not settled: it is reported in the batch result and it goes out again when the claim
   expires.
8. Adapters: memory and PostgreSQL. The table is in the specification and is the same in both
   packages.

## Consequences

- Delivery is at least once: if the process crashes between delivering and settling, the message
  goes out again with the same `id`. The receiver recognizes it because it reserves the event.
- There is no ordering among the messages of a single endpoint.
- An entry that always fails before the attempt goes out again every time its claim expires.
  It stays visible in the result of each batch; deciding when to discard it is up to the
  integrator.
- The claim has to last longer than a whole batch: the limit times the timeout of one attempt.
  With the default values, ten deliveries of twenty seconds fit within the three hundred of the
  claim.
- SQLite, Redis and the key-value stores do not have an outbox yet.
