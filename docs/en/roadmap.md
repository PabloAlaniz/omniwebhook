# Roadmap

> **Translation.** This is a translation of the [Spanish original](../roadmap.md). If the two disagree, the Spanish text wins.

Three two-week sprints. Each one closes with a published minor version and leaves the repository
in a state that is coherent on its own: if the next one is delayed, the previous one is still useful.

The order is not arbitrary. First, what already exists is hardened, because everything that comes
afterwards inherits that base. Then the places where you can receive are widened, which is where
almost everyone who adopts the package comes in. Last, sending is completed, which is what asks for
the most new design.

The rules in [CONTRIBUTING.md](../../CONTRIBUTING.en.md) apply to every item: a change in
behavior starts in the specification and in the vectors, reaches both packages in the same
pull request, and a new design decision is a new file in [`adr/`](../adr/).

| Sprint | Theme | What changes for whoever uses the package |
|---|---|---|
| 1 | Solid base | Nothing breaks; there are more verified guarantees and explicit limits |
| 2 | Receiving in more places | More frameworks, more senders, more stores and testing helpers |
| 3 | Sending end to end | From "one attempt" to a complete, observable and operable delivery |

## Sprint 1: solid base

**Status: done, except for what is marked below as pending.**

**Goal.** For the repository to follow the usual practices of a published security package, and
for the limits that are implicit today to be in the specification.

### Supply chain

- **Automatic dependency updates**, grouped by ecosystem (npm, uv and the workflow's actions),
  with the actions always pinned by hash as they have been so far.
- **Static security analysis** on every pull request and on `main`, for TypeScript and Python.
- **Periodic assessment of the repository's security practices** with
  [OpenSSF Scorecard](https://scorecard.dev/), with the result published as a badge in the
  README.
- **Provenance attestations in both registries**, requested explicitly in the publishing
  workflow, and one SBOM per package attached to each version.
- **Dependency review in the pull request**: it fails if a dependency comes in with a known
  vulnerability or with a license incompatible with MIT.

### Tougher tests

- **Property-based tests** for whatever parses someone else's input: the headers with pairs,
  the grammar of the destination URL, IP addresses, `retry-after` and the secrets. The minimum
  property is that an exception is never thrown and that the result is always one of the defined ones.
- **Scheduled differential fuzzing.** The interoperability test already compares the two packages
  with random variations; it now runs every night with a new seed and many more rounds, and a
  difference opens an issue with the seed to reproduce it. The first long run found
  one: an `xn--` label that is not valid Punycode passes the grammar of the destination URL, and
  the parser of one of the platforms rejects it. No request goes out, so today it is
  accepted as a safe failure. **Pending:** decide in the specification whether that URL must be
  `invalid_url`.
- **Coverage threshold for the adapters as well**, not only for the domain and the application.
- **Runtime matrix.** A smoke test that only uses web APIs goes through a complete cycle
  in Deno and in Bun, in addition to Node. **Pending:** the same inside a Worker.

### Explicit limits in the specification

- **Maximum body size when receiving.** A new outcome, with suggested status 413, that is
  decided before computing the signature. The limit is configurable and has a default value.
- **Maximum payload size when sending**, with a conservative default value: small payloads
  are the recommendation of the output format.
- **The endpoint's response is not read beyond what is necessary.** It is now written down that the
  body of the response is discarded or read up to a cap, so that an endpoint cannot exhaust memory.
- **Its own `user-agent` header when sending**, with the name and the version of the package, so that
  the receiver can identify the traffic. It joins the headers that the integrator cannot
  replace.

### Project health

- Issue templates (bug, new scheme, question) and a pull request template with the checklist from
  [CONTRIBUTING.md](../../CONTRIBUTING.en.md).
- Code of conduct and a file of review owners.
- Written compatibility policy: what is public API, which versions of Node and of Python are
  supported and for how long, and how a deprecation is announced before 1.0.

**Done when:** the repository's security assessment flags nothing pending that depends
on the code, the nightly fuzzing has gone a week without differences, and the four limits have a
section in the specification, vectors and an adapter in both packages.

## Sprint 2: receiving in more places

**Goal.** For integrating reception to be one line in the framework already in use, with the sender
you already have, and for testing that integration not to require writing the signature by hand.

**Status: done, except for what each item marks as pending.**

### Entry adapters

The problem they solve is always the same and is already named in the
[guide to receiving](recibir.md): getting to the raw body. Each adapter is a separate entry
module, with no mandatory dependency.

- **Done. TypeScript:** Node's `IncomingMessage` and `ServerResponse` (covers the frameworks
  built on top of them) and a helper for the frameworks that already hand over the body as a `Buffer`.
- **Done. Python:** WSGI (covers Flask and any other) and Django.
- **Done. Runnable examples** in [`examples/`](../../examples/): `node:http`, WSGI, Starlette and
  Django. Continuous integration (CI) starts each one and sends it a signed event, the same one
  repeated and one with another secret. **Pending:** one for the Fetch API inside a Worker, which
  goes together with the smoke test in Workers from sprint 1.

### Signature schemes

- **Done. Asymmetric signature of the standard format** for verifying. It is the current variant of the
  format, `v2a` (Ed25519 over the SHA-256 of the content, with the endpoint identifier
  in front); the previous one, `v1a`, is obsolete and is not implemented. It is a separate scheme,
  `standard-v2a`, and in Python it uses `cryptography` as an optional dependency. See
  [decision 0007](adr/0007-firma-asimetrica.md).
- **Three of four done. Four more senders**, chosen by demand and for covering variants that
  are not there today. Done: timestamp in a separate header with a version prefix (Slack), HMAC
  in base64 over the body (Shopify) and a public key per sender (Discord). Postponed, outside
  this sprint: signature over the URL plus the parameters, which requires keeping the full URL in the
  incoming request and uses HMAC-SHA1. Each one comes in through [the usual path](agregar-un-esquema.md), citing the
  sender's public documentation.
- **Done. Several senders on the same route.** A composite verifier that chooses the scheme by the
  headers present and that rejects as `ambiguous` a request that matches more than one.

### Idempotency stores

- **Done. Redis.** Each operation is a script and the entries delete themselves. The two packages
  run the same scripts and pass the store contract against a real Redis.
- **Done. Store on top of any key-value store with expiry.** A single store against a
  port of three methods, with clients for DynamoDB and Workers KV, and an in-memory one as a
  reference. It says which guarantee it gives: full if the client writes conditionally, reduced if
  not. See [decision 0008](adr/0008-almacen-clave-valor.md). **Pending:** test the
  DynamoDB and Workers KV clients against the service; today they run against in-memory doubles.

### Testing helpers

- **Done. One testing module per package** (`omniwebhook/testing`, `omniwebhook.testing`) that builds a
  valid signed request for any scheme, and its invalid variants: expired, with a tampered
  signature, repeated. It comes from the same rules as the vector generator.
- **Done. A minimal command line (CLI)**, the same in both packages: sign a body,
  verify a saved request and send a signed request to a local URL. What one signs, the
  other verifies.

### What happens after verifying

- **Done. Optional payload validation.** The receiver accepts a validator: in TypeScript, a
  schema with the common interface of the schema libraries; in Python, a function that returns
  the value or raises. A payload that does not validate is an outcome of its own, `unprocessable`. It is validated
  after verifying and before reserving, so it does not write to the store.
- **Done. Observation port** for reception: the integrator receives each outcome with its
  duration and the event key, without secrets or bodies. It is the basis of the telemetry in
  sprint 3. For sending it was not needed: the delivery ledger already receives each attempt.

**Done when:** each new adapter and each new scheme have vectors, the examples run in
continuous integration (CI), and the interoperability test covers the asymmetric signature in both
directions.

## Sprint 3: sending end to end

**Goal.** The package handled one attempt and said when the next one was due. This sprint
adds, as optional pieces, what is needed to operate deliveries in production without
rewriting it in every project.

**Status: in progress.** Agreed order: outbox and dispatch, endpoint health, event types,
asymmetric signature when sending, telemetry and, last, documentation in English and criteria for
1.0. Dated rotation, catalog in OpenAPI and documentation site are left for later.

### From one attempt to a delivery

- **Done. Transactional outbox.** A port of three operations (enqueue, claim,
  close) and its table in the specification, shared between packages. Enqueue accepts the
  integrator's transaction. Adapters: memory and PostgreSQL.
- **Done. Dispatching a batch.** `DispatchDue` claims what is pending and already due, makes one
  attempt per delivery and closes it with the outcome. It brings no loop and no scheduler. See
  [decision 0009](adr/0009-bandeja-de-salida.md). **Pending:** outbox on SQLite.
- **Pending. Order and concurrency per endpoint.** A cap on simultaneous deliveries per endpoint,
  so as not to knock over a slow receiver.

### Endpoint health

- **Done. Automatic disabling.** The specification defines when an endpoint is considered
  down: a 410, or enough consecutive failures throughout a whole window. The package computes it
  from the delivery ledger and reports it in the result of each batch; storing that state and
  notifying the endpoint's owner remains up to the integrator.
- **Done. Re-enabling and resending.** Health counts from the moment of re-enabling, and
  the outbox resends, by time range, what was closed without being delivered, with the same message
  `id`.

### Subscriptions

- **Done. Event types.** A type has the form `grupo.accion`, at any depth, and
  an endpoint declares which ones it subscribes to with patterns, with a wildcard per group. Filtering is
  a pure function of the domain, with vectors.
- **Postponed. Event catalog.** The types are declared with their payload schema, and from there comes an
  [OpenAPI](https://www.openapis.org/) document with the `webhooks` section, so that the receiver
  can generate their types.

### Signature and transport

- **Done. Asymmetric signature when sending.** `standardKeySigner` signs with a private key; the
  receiver keeps the public one. A combined signer sends both signatures together to migrate. The
  package generates pairs and derives the public key. See
  [decision 0010](adr/0010-firma-asimetrica-al-emitir.md).
- **Postponed. Dated rotation.** A previous secret stops signing on its own after a deadline, instead of
  depending on someone removing it from the list.

### Observability

- **Done. Telemetry with [OpenTelemetry](https://opentelemetry.io/)**, as optional
  adapters: metrics of receptions by outcome and of attempts by class and status, with their
  duration, and one HTTP client span per attempt with the attributes of the semantic
  conventions. The names are the same in both packages. See the [guide](telemetria.md).
- **Done. Trace context propagation** in the `traceparent` header.

### Documentation to get to 1.0

- **Done. Documentation in English** in addition to the Spanish one: all of it, not only the README, the guides (`docs/en/`)
  and the specification (`spec/SPEC.en.md`). Spanish remains the original. The examples
  go through the type checker, and another checker makes continuous integration (CI) fail if
  a translation stops having the same headings, tables and code blocks as its original.
- **Done. README in Simplified Chinese and in Brazilian Portuguese.** They are translations, with the
  Spanish original as the reference, and their examples go through the checker. The guides and the
  specification are not translated into these languages. **Pending:** have them reviewed by someone who speaks
  each language.
- **Postponed. Documentation site** generated from the repository, with an API reference extracted from
  the types.
- **Pending. Guide to implementing the specification in another language**, with the vectors published as a
  versioned artifact so they can be consumed without cloning the repository.
- **Done. Criteria for 1.0** written on [their own page](criterios-1.0.md): what has to
  be there, what is left out and what will never be there.

**Done when:** a complete example enqueues inside a transaction, delivers with the
dispatcher, disables an endpoint that is down and shows the trace end to end; and the
interoperability test checks that one package dispatches what the other enqueued.

## What is left out

- **A service to deploy.** The package is a library: it brings no server, dashboard or administration
  API.
- **A scheduler or a queue of its own.** The dispatcher relies on whatever is already in use.
- **A third language.** The guide and the published vectors leave it prepared, but it is not part of
  these three sprints.
- **A mode that skips verification.** Not even for development: that is what the testing helpers are for.
