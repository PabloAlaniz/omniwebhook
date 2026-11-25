# omniwebhook specification

> **Translation.** This is a translation of the [Spanish original](SPEC.md). If the two disagree, the Spanish text is the specification.
>
> Code and literals are copied unchanged from the original, so placeholders inside them stay in
> Spanish: `cuerpo` is the body, `clave=valor` is key=value, `ahora` is now, `marca` is the
> timestamp, `espera` is the wait, `esquema` is the scheme, `destino` is the endpoint, `mensaje` is
> the message, `en minúsculas` means lowercase, and `pedido.creado` reads "order.created".

Specification version: `0` (see [`VERSION`](VERSION)). Until version `1` it can change
between minor versions of the packages.

This document defines the behavior shared by all the packages. The vectors in
[`vectors/`](vectors/) make it verifiable: a package conforms to the specification if it passes
all of them.

The words MUST, MUST NOT, SHOULD and MAY are used with their usual meaning in normative
documents.

## 1. The two rules

1. **Nothing is processed without being verified.** There is no configuration that skips
   verification. Without a usable secret, the outcome is a rejection. When the scheme carries a
   signed timestamp, checking that it is recent is part of verifying and cannot be turned off.
2. **Each event takes effect only once.** The event is reserved before it is processed. If
   processing fails, the reservation is released so that the sender's retry can process it.

## 2. Terms

- **Sender**: whoever sends the webhook. **Receiver**: whoever receives it.
- **Raw body**: the bytes of the HTTP body as they arrived, before they are parsed.
- **Scheme**: a signature format. Each scheme knows how to verify and says what the event key is.
- **Event key**: the text that identifies an event so that it is not processed twice.
- **Now**: the current time in seconds since the Unix epoch. It is always injected.

## 3. Incoming request

An incoming request has:

- `headers`: names are case-insensitive. A name can carry more than one value.
- `query`: the URL parameters. A name can carry more than one value.
- `body`: the raw body, in bytes.

A header value or a parameter value is used without leading or trailing spaces. A value that is
empty after trimming is equivalent to the field being absent.

Throughout this document, "space" is the space character (U+0020) or the tab (U+0009), and
nothing else. Any other character, even if it looks blank, is part of the value.

## 4. Verification outcome

Verifying never throws an exception because of the request. It returns one of these outcomes:

| Outcome | Meaning |
|---|---|
| `ok` | The signature is valid and, if the scheme carries a timestamp, it is recent |
| `unconfigured` | There are no secrets, or one of them cannot be used |
| `missing` | A header or a parameter that the scheme requires is missing |
| `ambiguous` | A field that must be unique arrived more than once |
| `malformed` | A field is present but does not have the expected form |
| `invalid` | No signature matches |
| `stale` | The signature is valid but the timestamp is outside the tolerance |

With `ok` the outcome also carries `event_key` (always) and `timestamp` (in seconds, or null if
the scheme does not carry a timestamp).

### 4.1. Order of the checks

The checks are made in this order and the first one that fails is returned:

1. `unconfigured`
2. `missing`
3. `ambiguous`
4. `malformed`
5. `invalid`
6. `stale`

Freshness is evaluated last: `stale` is only reported for a request whose signature is valid.

### 4.2. Secrets

- Each scheme receives a list of secrets. The signature is valid if it matches any of them; this
  is how a secret is rotated without interrupting service.
- An empty list, an empty secret or a secret that the scheme cannot interpret give
  `unconfigured` for all requests. It is enough for one in the list to be unusable.
- A secret MUST NOT appear in an outcome, an error or a log.

### 4.3. Signature comparison

- The expected signature is encoded as text and compared with the received one in constant time.
- In hexadecimal, the expected one is in lowercase and the received one is converted to lowercase
  before comparing.
- In base64 the standard alphabet with padding is used and the comparison is exact.
- A received signature with any other form simply does not match. It is not a separate error.

### 4.4. Freshness

- The tolerance is expressed in seconds. The default is `300`.
- The tolerance MUST be an integer greater than zero. An invalid value is a configuration error
  when the scheme is built, not an outcome.
- A request is `stale` if `|ahora - marca| > tolerancia`. This applies equally to a timestamp in
  the past and to one in the future.
- Schemes without a signed timestamp cannot check freshness. In them the protection against
  replay is the reservation of the event (section 6).

### 4.5. Repeated fields

It is `ambiguous`:

- a header or a parameter that the scheme uses and that arrives with more than one value;
- inside a header with `clave=valor` pairs, a key that must be unique and appears more than
  once.

A verifier MUST NOT pick one of the repeated values.

### 4.5.1. Headers with pairs

A header with `clave=valor` pairs is split on commas. Each part is divided at the first `=` and
the spaces of the key and of the value are trimmed. A part without `=`, with an empty key or with
an empty value is ignored.

### 4.6. Event key

- The key always starts with the name of the scheme and `:`.
- When the scheme does not find an identifier, it uses the body fingerprint:
  `<esquema>:sha256:<SHA-256 del cuerpo crudo en hexadecimal en minúsculas>`.
- The integrator MAY replace the key with one of their own computed from the verified request.

### 4.7. Several schemes on one route

A composite verifier serves more than one sender on a single URL. It receives a list of routes;
each route is the name of a header and a verifier.

- A route matches a request if its header arrives with at least one value that is not empty
  (section 3).
- If no route matches, the outcome is `missing`.
- If more than one matches, the outcome is `ambiguous`. One MUST NOT be picked, not even when
  only one of the signatures would turn out to be valid.
- If exactly one matches, the outcome is that of its verifier, unchanged.

A request MUST NOT be tried against one scheme after another until one of them accepts it: that
would give whoever sends the request the ability to choose which rules it is verified with.

An empty list of routes, an empty header or a header repeated across routes (case-insensitively)
is a configuration error when it is built, not an outcome.

## 5. Schemes

All of them use HMAC-SHA256, except `standard-v2a` (section 5.10) and `discord` (section 5.11),
which verify with a public key, and the shared-token ones (sections 5.12 to 5.14), which sign
nothing. "Body" is always the raw body.

### 5.1. `standard`

The [Standard Webhooks](https://www.standardwebhooks.com/) format, with the symmetric signature
`v1`.

- Required headers: `webhook-id`, `webhook-timestamp`, `webhook-signature`.
- Secret: the `whsec_` prefix is optional; the rest is base64 and, decoded, is the key. It is
  usable if, without the prefix, it is not empty, its length is a multiple of four and it matches
  `^[A-Za-z0-9+/]*={0,2}$`.
- `webhook-timestamp` MUST match `^[0-9]{1,11}$`. Otherwise, `malformed`.
- `webhook-signature` carries one or more signatures separated by spaces. Only those that start
  with `v1,` count; the rest are ignored. If there is no `v1,` one, `malformed`.
- Signed content: `<webhook-id>.<webhook-timestamp>.<cuerpo>`.
- Signature: base64 of the HMAC.
- Timestamp: `webhook-timestamp`, in seconds.
- Event key: `standard:<webhook-id>`.

This is also the scheme used to sign what is sent (section 7).

### 5.2. `stripe`

- Required header: `stripe-signature`, with `clave=valor` pairs (section 4.5.1).
- The keys `t` and `v1` count. Any other is ignored.
- Without `t` or without any `v1`, `malformed`. More than one `t`, `ambiguous`. There can be
  several `v1`.
- `t` MUST match `^[0-9]{1,11}$`. Otherwise, `malformed`.
- Secret: the complete text, in UTF-8, is the key.
- Signed content: `<t>.<cuerpo>`.
- Signature: hexadecimal of the HMAC. It is valid if it matches any `v1`.
- Timestamp: `t`, in seconds.
- Event key: `stripe:<id>`, where `id` is the `id` field of the body if the body is a JSON object
  with an `id` that is a non-empty string. Otherwise, the body fingerprint.
  The body is parsed as strict JSON in UTF-8: with a byte order mark at the start, or with values
  that are not JSON such as `NaN` or `Infinity`, the fingerprint is used. With nesting so deep
  that the platform cannot parse it, also. The size of a number does not change the outcome.

### 5.3. `mercadopago`

- Required header: `x-signature`, with `clave=valor` pairs (section 4.5.1). The keys are
  compared in lowercase.
- Optional data: the `x-request-id` header and the `data.id` parameter of the URL.
- The keys `ts` and `v1` count. Without either of the two, `malformed`. Either one repeated,
  `ambiguous`.
- `ts` MUST match `^[0-9]{1,15}$`. Otherwise, `malformed`.
- Secret: the complete text, in UTF-8, is the key.
- Signed content (the "manifest"): the following are built, in this order and only if the field
  is present, `id:<data.id en minúsculas>`, `request-id:<x-request-id>` and `ts:<ts>`; they are
  joined with `;` and a final `;` is appended. Example: `id:123;request-id:abc;ts:1700000000;`.
- Signature: hexadecimal of the HMAC.
- Timestamp: `ts`. A value greater than or equal to `100000000000` is in milliseconds and is
  divided by one thousand discarding the remainder; a smaller one is in seconds.
- Event key: `mercadopago:<data.id en minúsculas>:<x-request-id>`, with empty text in the place
  of the field that is missing. If both are missing, `mercadopago:ts:<ts>`.

The signature of this scheme **does not cover the body**. Whoever processes the event SHOULD
treat it as a change notice and query the sender for the resource, and MAY replace the event key
with one that includes the notice type. Notifications that the sender does not sign cannot be
verified with this scheme.

### 5.4. `github`

- Required header: `x-hub-signature-256`, with the form `sha256=<hexadecimal>`. Without that
  prefix, `malformed`.
- Secret: the complete text, in UTF-8, is the key.
- Signed content: the body.
- No timestamp.
- Event key: `github:<x-github-delivery>` if the header is present. Otherwise, the body
  fingerprint.

### 5.5. `creem`

- Required header: `creem-signature`, in hexadecimal.
- Secret: the complete text, in UTF-8, is the key.
- Signed content: the body.
- No timestamp.
- Event key: `creem:<id>`, with the same rule for the `id` field as in `stripe`.

### 5.6. `tiktok`

- Required header: `tiktok-signature`, with `clave=valor` pairs (section 4.5.1).
- The keys `t` and `s` count. Any other is ignored.
- Without `t` or without `s`, `malformed`. Either of the two repeated, `ambiguous`.
- `t` MUST match `^[0-9]{1,11}$`. Otherwise, `malformed`.
- Secret: the complete text, in UTF-8, is the key (the app's *client secret*).
- Signed content: `<t>.<cuerpo>`.
- Signature: hexadecimal of the HMAC.
- Timestamp: `t`, in seconds.
- Event key: the body fingerprint. The sender does not send a delivery identifier and the body
  does not carry an `id`; retries arrive with the same body.

### 5.7. `hmac-body`

A generic scheme for senders that sign only the body. It is configured with:

| Option | Meaning | Default |
|---|---|---|
| `name` | The name of the scheme in the event key | `hmac-body` |
| `header` | The header that carries the signature | required |
| `prefix` | A fixed text before the signature | empty |
| `encoding` | `hex` or `base64` | `hex` |
| `id_header` | The header that identifies the event | none |

- If `prefix` is not empty and the value does not start with it, `malformed`.
- Secret: the complete text, in UTF-8, is the key.
- Signed content: the body. No timestamp.
- Event key: `<name>:<valor de id_header>` if it is configured and arrives. Otherwise, the body
  fingerprint.

### 5.8. `slack`

- Required headers: `x-slack-signature` and `x-slack-request-timestamp`.
- `x-slack-request-timestamp` MUST match `^[0-9]{1,11}$`. Otherwise, `malformed`.
- `x-slack-signature` MUST start with `v0=`, exactly as written. Otherwise, `malformed`. What
  follows is the signature.
- Secret: the complete text, in UTF-8, is the key (the app's *signing secret*).
- Signed content: `v0:<x-slack-request-timestamp>:<cuerpo>`.
- Signature: hexadecimal of the HMAC.
- Timestamp: `x-slack-request-timestamp`, in seconds.
- Event key: `slack:<event_id>`, with the rule for the `id` field of `stripe` applied to the
  `event_id` field of the body. Requests that are not events (commands, interactions) arrive as
  a form and do not carry that field: their key is the body fingerprint.

### 5.9. `shopify`

- Required header: `x-shopify-hmac-sha256`. Optional: `x-shopify-webhook-id`.
- Secret: the complete text, in UTF-8, is the key (the app's *client secret*).
- Signed content: the body.
- Signature: base64 of the HMAC, with padding. It is compared as it arrived.
- No timestamp.
- Event key: `shopify:<x-shopify-webhook-id>` if it arrives. Otherwise, the body fingerprint.
  That identifier is repeated across the retries of the same webhook.

### 5.10. `standard-v2a`

The [Standard Webhooks](https://www.standardwebhooks.com/) format with the asymmetric signature
`v2a` (Ed25519). The receiver stores a public key: with it the receiver can verify, but not sign.

It is configured with a list of public keys and with the `endpoint_id`: the identifier that the
sender assigned to this endpoint when creating it.

- Required headers: `webhook-id`, `webhook-timestamp`, `webhook-signature`.
- Public key: the `whpk_` prefix is mandatory; the rest is base64 and, decoded, is the 32 bytes
  of the key. It is usable if, without the prefix, it matches `^[A-Za-z0-9+/]*={0,2}$`, its
  length is a multiple of four and it decodes to exactly 32 bytes. The rules of section 4.2 apply
  equally: an empty list or an unusable key give `unconfigured`.
- `endpoint_id` MUST NOT be empty or contain `.`. Otherwise, it is a configuration error when the
  scheme is built. It is never taken from the request.
- `webhook-timestamp` MUST match `^[0-9]{1,11}$`. Otherwise, `malformed`.
- `webhook-signature` carries one or more signatures separated by spaces. Only those that start
  with `v2a,` count; the rest are ignored, including the symmetric `v1,` ones and those of the
  previous version `v1a,`. If there is no `v2a,` one, `malformed`.
- Signed content: the 32 raw bytes of
  `SHA-256(<endpoint_id>.<webhook-id>.<webhook-timestamp>.<cuerpo>)`.
- Signature: base64, with padding, of the 64 bytes of the Ed25519 signature (RFC 8032) of that
  content.
- The signature is valid if any of the received ones verifies with any of the keys. A signature
  that is not base64 or that is not 64 bytes long simply does not verify: it is not a separate
  error. The text comparison of section 4.3 does not apply here.
- Timestamp: `webhook-timestamp`, in seconds.
- Event key: `standard:<webhook-id>`, the same as with the symmetric signature: it is the same
  sender and the same message.

### 5.11. `discord`

Signature with Ed25519. It is configured with a list of public keys: that of the application.

- Required headers: `x-signature-ed25519` and `x-signature-timestamp`.
- Public key: 64 hexadecimal digits, in uppercase or lowercase, which are the 32 bytes of the
  key. Any other form gives `unconfigured`, with the rules of section 4.2.
- `x-signature-timestamp` MUST match `^[0-9]{1,11}$`. Otherwise, `malformed`.
- Signed content: `<x-signature-timestamp><cuerpo>`, with no separator.
- Signature: the 64 bytes of the Ed25519 signature (RFC 8032) of that content, in hexadecimal, in
  uppercase or lowercase. One that is not 128 hexadecimal digits simply does not verify.
- Timestamp: `x-signature-timestamp`, in seconds. The sender does not set a tolerance; since the
  timestamp is signed, the one of section 4.4 applies.
- Event key: `discord:<id>`, with the same rule for the `id` field as in `stripe`. Events that
  do not carry an `id` use the body fingerprint.

### 5.12. `shared-token`

A generic scheme for senders that do not sign: they send, as is, a secret token that the receiver
chose when registering the webhook. It is configured with:

| Option | Meaning | Default |
|---|---|---|
| `name` | The name of the scheme in the event key | `shared-token` |
| `header` | The header that carries the token | none |
| `query` | The URL parameter that carries the token | none |
| `id_header` | The header that identifies the event | none |

- Exactly one of `header` and `query` MUST be configured. Both, or neither, is a configuration
  error when building the scheme, not an outcome.
- Required data: the token, in the configured place. If it is not there, `missing`; if it arrives
  repeated, `ambiguous`. A token that arrives in the other place does not count.
- Secret: the complete text, in UTF-8. The request is valid if the received token, already trimmed
  (section 3), is exactly equal to one of the secrets. The comparison is case-sensitive and is done
  in constant time (section 4.3). If it matches none, `invalid`.
- There is no `malformed`: a token with another shape simply does not match.
- No timestamp.
- Event key: `<name>:<valor de id_header>` if it is configured and arrives. Otherwise, the body
  fingerprint.

The token **covers nothing in the request**: not the body, not the other headers, not the header
that identifies the event. It only proves that the caller knows the secret. Whoever processes the
event SHOULD treat it as a change notice and query the resource from the sender. A token that
travels in the URL usually ends up in access logs; a header SHOULD be preferred when the sender
allows it.

### 5.13. `google-channel`

The [notification channels](https://developers.google.com/workspace/calendar/api/guides/push) of
the Google Workspace APIs (Calendar, Drive and others). It is a shared token (section 5.12) with
fixed places: the token is the one the receiver chose when creating the channel.

- Required headers: `x-goog-channel-token`, `x-goog-channel-id` and `x-goog-message-number`.
  Any of them missing, `missing`; any of them repeated, `ambiguous`.
- `x-goog-message-number` MUST match `^[0-9]{1,20}$`. Otherwise, `malformed`.
- Secret and comparison: as in `shared-token`, against `x-goog-channel-token`.
- No timestamp.
- Event key: `google-channel:<x-goog-channel-id>:<x-goog-message-number>`, with the number as it
  arrived.

A channel created without a token cannot be verified with this scheme. What section 5.12 says
applies: the token does not cover the body or the other headers, and the notification SHOULD be
treated as a signal to query the changes from the API.

### 5.14. `google-pubsub`

The [push subscriptions](https://cloud.google.com/pubsub/docs/push) of Google Cloud Pub/Sub, which
is how, among others, Gmail notifications arrive. It is a shared token (section 5.12) that travels
in the subscription's push URL. It is configured with:

| Option | Meaning | Default |
|---|---|---|
| `query` | The URL parameter that carries the token | `token` |

- Required data: the configured parameter. If it is not there, `missing`; if it arrives repeated,
  `ambiguous`.
- Secret and comparison: as in `shared-token`.
- No timestamp.
- Event key: `google-pubsub:<id>`. The body is parsed as strict JSON, with the same rules as in
  `stripe`. If it is an object whose `message` field is an object, `id` is its `messageId` field
  if it is a non-empty string; otherwise, its `message_id` field if it is a non-empty string. In
  any other case, the body fingerprint.

This scheme **does not verify** the identity token (a JWT with an asymmetric signature) that
Pub/Sub can send in the `authorization` header: whoever needs it checks it separately. What
section 5.12 says about what the token does not cover and about tokens in the URL applies.

## 6. Receiving: processing only once

### 6.1. The idempotency store

It is a port with three operations. All of them MUST be atomic.

- `claim(key, token, now, lease_seconds)` returns `claimed`, `in_progress` or `duplicate`.
- `complete(key, token, now, retention_seconds)` returns whether it was applied.
- `release(key, token)` returns whether it was applied.

An entry is **reserved** until its lease expires, or **completed** until its retention expires.
An entry expires when `now` is greater than or equal to its expiry. Rules of `claim`:

| State of the key | Result | Effect |
|---|---|---|
| It does not exist, or it exists but has already expired | `claimed` | It becomes reserved by `token` until `now + lease_seconds` |
| Reserved and not expired | `in_progress` | None |
| Completed and not expired | `duplicate` | None |

`complete` and `release` are only applied if the stored entry is a reservation made with the same
`token`, even if its lease has expired. This way, whoever was delayed can finish if nobody claimed
the key, and whoever lost their reservation does not overwrite whoever claimed it afterwards.
`complete` leaves the entry completed until `now + retention_seconds`; `release` deletes it.

Default values: `lease_seconds = 300` and `retention_seconds = 604800` (seven days).

### 6.2. The use case

Given a request, a scheme, a store and a function that processes the event:

1. If the body has more than `max_body_bytes` bytes, return `too_large` and stop.
2. Verify with the scheme. If the outcome is not `ok`, return it and stop.
3. Determine the event key.
4. If there is a payload validator: parse the body as JSON and pass it to the validator. If the
   body is not JSON or the validator rejects it, return `unprocessable` and stop.
5. `claim`. If it returns `duplicate` or `in_progress`, return that outcome and stop.
6. Run the function that processes the event.
7. If it finishes successfully: `complete` and return `ok`.
8. If it fails: `release` and return `failed` with the error attached.

The function that processes the event MUST NOT run if step 2 did not give `ok`, step 4 gave
`unprocessable` or step 5 did not give `claimed`.

The payload validator is optional. It receives the already parsed body and accepts it, returning
the value that the function that processes the event works with, or rejects it.

- The payload is validated after verifying: an unauthenticated body is not parsed.
- It is validated before reserving: an invalid payload does not write to the store. There is
  nothing to release, and if the sender retries, the retry gives `unprocessable` again.
- The body is parsed as strict JSON in UTF-8, with the same rules as the `id` field of
  section 5.2: with a byte order mark, with `NaN` or `Infinity`, or empty, it is not JSON.
- `unprocessable` carries the event key and the reason for the rejection, so that it can be
  logged.

`max_body_bytes` is `1048576` by default (1 MiB) and MUST be an integer greater than zero. The
size is checked before anything else, including the secrets: computing a signature over an
arbitrarily large body is work that an unauthenticated request must not be able to cause.

This limit bounds the work of verifying, not the memory: when the use case receives the request,
the body has already been read. The server or the framework that reads it SHOULD have its own
limit, equal or smaller.

### 6.3. Suggested HTTP response

| Outcome | Status | Why |
|---|---|---|
| `ok` | 200 | Processed |
| `duplicate` | 200 | It had already been processed: the sender has to stop retrying |
| `in_progress` | 409 | Another process is processing it: it is better for the sender to retry |
| `missing`, `ambiguous`, `malformed`, `invalid`, `stale` | 401 | The origin could not be checked |
| `too_large` | 413 | The body exceeds the maximum: retrying is not going to fix it |
| `unprocessable` | 422 | The signature is valid but the payload does not have the expected form: retrying is not going to fix it |
| `unconfigured` | 500 | It is a problem of the receiver: it is better for the sender to retry |
| `failed` | 500 | Processing failed and the reservation was released |

The body of the response MUST NOT say which of the checks failed.

### 6.4. Observing

The integrator MAY register an observer of the reception. After each request, whatever the
outcome, the observer receives:

| Field | Content |
|---|---|
| `outcome` | The outcome (sections 4 and 6.2) |
| `event_key` | The event key, or null if the request did not get as far as being verified |
| `duration_ms` | How long the complete reception took, including the processing |

- The observer MUST NOT receive the body, the headers or any secret.
- The observer does not change the outcome. If it fails, its error is discarded: a failure while
  measuring cannot cause a webhook to be rejected or to be processed twice.
- It is called only once per request, after completing or releasing the reservation.

For sending there is no need for a separate port: the delivery ledger (section 8.4) already
receives each attempt with its class, its HTTP status and its duration.

## 7. Sending: signing

A message has `id`, `timestamp` (seconds) and `payload` (bytes).

- The `id` identifies the message, not the attempt: it stays the same across all the retries.
- The `id` MUST NOT be empty or contain `.`.
- The message is signed with the `standard` scheme and is sent with the headers `webhook-id`,
  `webhook-timestamp` and `webhook-signature`.
- The `timestamp` is that of the attempt: each retry is signed again with the current time.
- With more than one secret, one signature per secret is sent, separated by a space and in the
  order of the list.
- The body sent MUST be, byte for byte, the `payload` that was signed.
- The `payload` MUST NOT have more than `max_payload_bytes` bytes: `262144` by default (256 KiB),
  and it MUST be an integer greater than zero. A larger one is neither signed nor sent: it is an
  error of the integrator, the same as an invalid `id`, and it is not recorded in the ledger. The
  default value is smaller than the default `max_body_bytes` of section 6.2, so what one package
  sends the other receives without configuring anything.
- Each attempt carries a `user-agent` header with the form
  `omniwebhook/<versión del paquete> (<lenguaje>)`, where the language is `typescript` or
  `python`. For example, `omniwebhook/0.4.0 (python)`. It lets the receiver recognize the
  traffic; it is not a proof of origin, which is what the signature is for.
- The headers that the integrator adds MUST NOT replace or duplicate those of the signature, that
  of the content type or `user-agent`. Names are compared case-insensitively.

### 7.1. Asymmetric signature

The sender MAY sign with the asymmetric variant of the format, `v2a` (section 5.10): the sender
signs with a private key and the receiver verifies with the public one, with no shared secret.

- The message also carries the identifier of the endpoint, `endpoint_id`: the same one that is
  recorded in the ledger. The sender communicates it to the receiver together with the public
  key.
- `endpoint_id` MUST NOT be empty or contain `.`. Otherwise, nothing is signed:
  `invalid_endpoint`.
- Private key: the `whsk_` prefix is mandatory; the rest is base64 and, decoded, is the 32 bytes
  of the Ed25519 seed. With the same rules of form as the public key of section 5.10. Without
  keys, or with any unusable one, nothing is signed: `unconfigured`.
- The public key that corresponds to it is `whpk_` followed by the base64 of its 32 bytes.
- Signature: `v2a,` followed by the base64 of the Ed25519 signature of
  `SHA-256(<endpoint_id>.<id>.<timestamp>.<payload>)`.
- With more than one key, one signature per key is sent, separated by a space and in the order
  of the list.
- The checks go in this order: `invalid_id`, `invalid_timestamp`, `invalid_endpoint`,
  `unconfigured`.
- A private key MUST NOT appear in an outcome, an error or a log, and MUST NOT be shown to the
  receiver.

To migrate from one signature to the other, a single message MAY carry both: the signatures of
each variant go in the same `webhook-signature` header, separated by a space. Each receiver
looks only at those of its variant.

## 8. Sending: delivering

### 8.1. Destination URL policy

Before each attempt the URL and the addresses it resolves to are validated.

- The scheme MUST be `https`. `http` is only accepted if the configuration expressly allows it.
- The URL MUST NOT carry a user or a password.
- If the name is a literal IP address, that address is evaluated and nothing is resolved.
- Otherwise, the name is resolved to IP addresses. If any address is blocked, the attempt is
  rejected. If it does not resolve to any, also.
- If the resolution fails, instead of answering with no addresses, the attempt counts as a
  network error (section 8.2): it can be transient.
- The connection MUST be made to one of the validated addresses, not to a new resolution.
- Redirects are not followed.

Blocked ranges:

| IPv4 | IPv6 |
|---|---|
| `0.0.0.0/8`, `10.0.0.0/8`, `100.64.0.0/10`, `127.0.0.0/8` | `::/128`, `::1/128` |
| `169.254.0.0/16`, `172.16.0.0/12`, `192.0.0.0/24`, `192.0.2.0/24` | `64:ff9b::/96`, `100::/64` |
| `192.168.0.0/16`, `198.18.0.0/15`, `198.51.100.0/24`, `203.0.113.0/24` | `2001:db8::/32`, `fc00::/7` |
| `224.0.0.0/4`, `240.0.0.0/4` | `fe80::/10`, `ff00::/8` |

An IPv6 address that wraps an IPv4 one (`::ffff:0:0/96`) is evaluated by the IPv4 address it
contains.

#### Allowed networks

The configuration MAY carry a list of allowed networks, empty by default. It is for delivering
to services on a network of one's own, such as those of an installation on the same machine or
the same local network. An address is blocked if it is not an IP address, or if it falls in a
blocked range and does not fall in any allowed network.

The addresses of the cloud metadata services are never allowed, even if a network in the list
includes them:

| IPv4 | IPv6 |
|---|---|
| `169.254.0.0/16`, `100.100.100.200/32` | `fd00:ec2::254/128` |

An IPv6 address that wraps an IPv4 one is evaluated by the IPv4 address here too: it is compared
with the IPv4 networks in the list.

Each network is written `dirección/prefijo`:

- `dirección` is an IPv4 or an IPv6 address with the form of the grammar below, without brackets.
- `prefijo` is a decimal number without leading zeros, from 0 to 32 for IPv4 and from 0 to 128
  for IPv6.
- The bits of the address that fall outside the prefix MUST be zero: `10.0.0.0/8` yes,
  `10.0.0.1/8` no.
- An IPv6 network inside `::ffff:0:0/96` is not accepted: those addresses are evaluated by their
  IPv4 address.

A network that does not meet this is a configuration error and is rejected when the sender is
assembled, not on each attempt. Allowing a network that is not blocked changes nothing.

#### Form of the URL

The URL is not handed to the platform's URL parser until it has been checked that it has this
form, because parsers do not agree with each other when faced with an unusual URL and that
difference is exactly what someone who wants to reach an internal address exploits.

```
url       = esquema "://" [ usuario "@" ] host [ ":" puerto ] [ resto ]
esquema   = "http" / "https"                    ; sin distinguir mayúsculas
host      = "[" IPv6 "]" / IPv4 / nombre
nombre    = etiqueta *( "." etiqueta ) [ "." ]  ; hasta 253 caracteres
etiqueta  = 1*63( letra ASCII / dígito / "-" / "_" )
puerto    = 1*5 dígito                          ; hasta 65535
resto     = ( "/" / "?" / "#" ) cualquier cosa
```

- The URL MUST NOT contain the backslash, or characters from U+0000 to U+0020, or U+007F.
- `usuario` is everything before the last `@` of the part that goes between `://` and the
  `resto`.
- `IPv4` is four decimal numbers from 0 to 255 without leading zeros; `IPv6`, the usual notation,
  without a zone identifier. They are the only forms that count as a literal address.
- A `nombre` whose last label is a number (only digits, or `0x` followed by hexadecimal digits)
  is not accepted: there are parsers that read it as an address.
- A name with characters outside ASCII goes in its ASCII form (`xn--…`).
- The host is used in lowercase.

It is checked in this order:

1. Without a scheme at the start (`^[A-Za-z][A-Za-z0-9+.-]*:`), or with a forbidden character:
   `invalid_url`.
2. With a scheme that is not `https`, nor `http` with the express permission: `scheme`.
3. If what follows does not have the form above: `invalid_url`.
4. If it carries `usuario`, even if it is empty: `credentials`.

The result of the policy is `allowed` or the first reason for rejection, in this order:

| Reason | When |
|---|---|
| `invalid_url` | It does not have the form of a destination URL |
| `scheme` | The scheme is not `https`, nor `http` with the express permission |
| `credentials` | It carries a user or a password |
| `unresolved` | The name did not resolve to any address |
| `blocked_address` | Some address is blocked: in a blocked range and outside the allowed networks, or it is not an IP address |

The destination URL MUST NOT appear in an error or in a log.

### 8.2. Classification of the response

| What happened | Class | What follows |
|---|---|---|
| Status 2xx | `delivered` | Nothing more |
| Status 410 | `gone` | It is not retried and the endpoint is disabled |
| Status 408, 409, 425, 429 or 5xx | `retryable` | It is retried |
| Network error or timeout expired | `retryable` | It is retried |
| Any other status, including 3xx | `rejected` | It is not retried |
| The URL policy rejected the attempt | `blocked` | It is not retried |

The timeout is the deadline for the complete attempt, from the moment the connection starts
until the status of the response is available. It MUST NOT be a deadline per network operation: a
server that sends the response one byte at a time cannot stretch the attempt. The default is 20
seconds.

The body of the response MUST NOT be read. To classify the attempt, the status and the
`retry-after` header are enough: with that the connection is closed, and an endpoint cannot make
the sender spend memory or time by responding with a body that is huge or that does not end.

### 8.3. Retries

The retry policy is data: a list of waits in seconds between one attempt and the next. By
default:

```
[5, 300, 1800, 7200, 18000, 36000, 50400, 72000, 86400]
```

With that list there are ten attempts: the first one is immediate.

After attempt number `n` (the first one is 1) with class `retryable`:

- If `n` is greater than the length of the list, there are no more attempts: the delivery
  becomes `exhausted`.
- Otherwise, the base wait is element `n` of the list (counting from 1).
- If the response carried `retry-after`, the wait is the greater of the base and that value.
  `retry-after` can be an integer number of seconds (`^[0-9]+$`) or an HTTP date with the form
  `Sun, 06 Nov 1994 08:49:37 GMT`, which is converted to `fecha - ahora`. One that cannot be
  interpreted or that gives a negative value is ignored.
- The wait never exceeds `max_delay_seconds` (by default `86400`).
- A variation is added to the wait: `piso(espera × jitter_ratio × r)`, where `r` is a number in
  `[0, 1)` that is injected and `jitter_ratio` is `0.1` by default. The variation is applied
  after the cap.
- The next attempt is at `ahora + espera`.

### 8.4. The delivery ledger

It is a port. For each attempt it stores: the `id` of the message, the endpoint, the attempt
number, the class of the result, the HTTP status if there was one, the duration and when the next
one is due.

The state of a delivery is `pending`, `delivered`, `rejected`, `blocked`, `gone` or `exhausted`.

After each attempt, the state comes from the class of the result: `delivered`, `rejected`,
`blocked` and `gone` pass through as they are; `retryable` becomes `pending` if there is a next
attempt and `exhausted` if there is not.

Resending a delivery by hand is sending it again from attempt 1 with the same message `id`, so
that the receiver can recognize it.

#### The PostgreSQL table

A ledger on PostgreSQL MUST use this table, so that what one package records the other can read.
The default name is `omniwebhook_attempts`:

| Column | Type | Content |
|---|---|---|
| `id` | `bigint`, identity | The order in which it was recorded |
| `message_id` | `text` | The `id` of the message |
| `endpoint_id` | `text` | The identifier of the endpoint, never its URL |
| `attempt` | `integer` | The attempt number |
| `at` | `bigint` | When the attempt started, in seconds |
| `delivery_class` | `text` | The class of the result (section 8.2) |
| `state` | `text` | The state of the delivery after the attempt |
| `status` | `integer`, null | The HTTP status, if there was a response |
| `problem` | `text`, null | The reason from the URL policy, if it rejected the attempt |
| `duration_ms` | `bigint` | How long the attempt lasted |
| `next_at` | `bigint`, null | When the next attempt is due |

A resend repeats attempt numbers, so the key is `id` and not `(message_id, endpoint_id,
attempt)`. There is one index on `(message_id, endpoint_id)` and another on `(endpoint_id, at)`.

Reading the attempts of a message to an endpoint returns the rows in the order of `id`.

The package computes when the next attempt is due but does not execute it. The integrator can
schedule it with whatever they already use, or rely on the outbox.

### 8.5. The outbox

It is an optional port: it stores the pending deliveries so that they are not lost if the process
crashes, and hands them out without two processes delivering the same one. It is not a queue with
a scheduler: someone has to ask it for the next batch.

An entry is a message for an endpoint. It stores the `id` of the message, the identifier of the
endpoint (never its URL), the payload in bytes, the number of the next attempt, since when it is
available and its state. The pair `(id del mensaje, destino)` is unique.

The state is `pending` or a final one: `delivered`, `rejected`, `blocked`, `gone`, `exhausted`
(those of section 8.4) or `cancelled`, for a delivery that was discarded without being attempted.

It has four operations. All of them MUST be atomic.

- `enqueue(message_id, endpoint_id, payload, now)` returns whether it was enqueued. It creates
  the entry as `pending`, with attempt `1` and available from `now`. If the pair already exists,
  in any state, it changes nothing and returns false.
- `claim(token, now, limit, lease_seconds)` claims up to `limit` entries and returns them with
  their payload and their attempt number. The entries that can be claimed are the `pending` ones
  that are available (`now` greater than or equal to their time) and that are not claimed, or
  whose claim has expired (`now` greater than or equal to its expiry). They come out ordered by
  the time from which they are available and, for the same time, by the order in which they were
  enqueued. Each one becomes claimed by `token` until `now + lease_seconds`.
- `settle(message_id, endpoint_id, token, state, next_at)` returns whether it was applied. It is
  only applied if the entry is `pending` and that same `token` claimed it, even if the lease has
  expired. With `state = pending`, the attempt number goes up by one, the entry becomes available
  from `next_at` and the claim is released. With a final state, it stays in that state.

- `requeue(endpoint_id, from, to, now)` returns how many entries it requeued. It covers those of
  that endpoint that were settled without being delivered (any final state except `delivered`)
  and whose availability time is between `from` and `to`, both included. Each one goes back to
  `pending`, with attempt `1` and available from `now`. The `id` of the message does not change:
  it is the resend of section 8.4.

The rules of the claim are those of the reservation of section 6.1: whoever was delayed can
settle if nobody claimed the entry, and whoever lost their claim does not overwrite whoever
claimed it afterwards.

Consequences that the integrator has to know:

- **At least once.** If the process crashes after delivering and before `settle`, the entry
  comes out again when the claim expires, with the same message `id`. That is what the receiver
  reserves the event for (section 6).
- **No order between messages.** Two messages for the same endpoint can arrive in any order: a
  retry delays one and not the other.
- `lease_seconds` MUST be greater than the time it can take to dispatch a whole batch.

#### Dispatching a batch

Given an outbox, a directory of endpoints and whoever makes the attempt (section 8):

1. `claim` with a new token.
2. For each entry, ask the directory for the endpoint. If it does not exist or is disabled,
   `settle` with `cancelled`, without attempting or recording anything.
3. If it exists, make an attempt with the attempt number of the entry.
4. `settle` with the state the delivery ended up in; if it is `pending`, with its `next_at`.

If the attempt does not get to be made because of an error of the integrator (section 7), the
entry is not settled: it comes out again when the claim expires, and the error is reported in the
result of the batch.

#### Endpoint health

The health of an endpoint is computed from the delivery ledger (section 8.4); it is not data that
is stored separately.

The **failure summary** of an endpoint since a time `since` looks at its attempts with `at`
greater than or equal to `since`, in the order in which they were recorded, and of those only the
ones after the last one with class `delivered`:

| Field | Content |
|---|---|
| `failures` | How many there are |
| `failing_since` | The smallest `at` among them; null if there are none |
| `gone` | Whether any of them has class `gone` |

`since` is `0` for an endpoint that was never disabled, and the time at which it was re-enabled
for one that was: this way what happened before does not disable it again.

With that summary, the current time and two parameters, `window_seconds` (by default `432000`,
five days) and `min_failures` (by default `5`), both integers greater than zero:

| Condition, in this order | State | Reason |
|---|---|---|
| `gone` | `disabled` | `gone` |
| `failures >= min_failures` and `ahora - failing_since >= window_seconds` | `disabled` | `failing` |
| `failures > 0` | `failing` | none |
| None | `healthy` | none |

Both things are needed, quantity and time: many failures in a short while are an outage that
recovers, and an isolated failure a week ago says nothing.

When dispatching a batch, after an attempt that was not delivered, the health of the endpoint is
computed. If it gives `disabled`, the result of the batch reports it. The package does not
disable anything on its own: storing that state, ceasing to resolve the endpoint and notifying
its owner is up to the integrator. As long as the directory keeps resolving it, deliveries to it
continue.

#### The PostgreSQL table

An outbox on PostgreSQL MUST use this table, so that what one package enqueues the other can
dispatch. The default name is `omniwebhook_outbox`:

| Column | Type | Content |
|---|---|---|
| `seq` | `bigint`, identity | The order in which it was enqueued |
| `message_id` | `text` | The `id` of the message |
| `endpoint_id` | `text` | The identifier of the endpoint, never its URL |
| `payload` | `bytea` | The body, byte for byte as it is going to be sent |
| `attempt` | `integer` | The number of the next attempt |
| `available_at` | `bigint` | Since when it can be claimed, in seconds |
| `state` | `text` | The state of the entry |
| `token` | `text`, null | Who has it claimed |
| `lease_expires_at` | `bigint`, null | Until when the claim is valid |

The key is `(message_id, endpoint_id)`. There is an index on `(state, available_at)`.

### 8.6. Event types

An event type names what happened, from the general to the particular: `pedido.creado`,
`pedido.item.agregado`. It lets each endpoint receive only what it is interested in.

```
tipo     = segmento *( "." segmento )
patrón   = "*" / segmento *( "." segmento ) [ ".*" ]
segmento = 1*( letra ASCII / dígito / "-" / "_" )
```

Both have at most 256 characters. They are compared case-sensitively.

A pattern matches a type like this:

| Pattern | Matches |
|---|---|
| `*` | Any type |
| `pedido.*` | The types that start with `pedido.`, at any depth. Not `pedido` alone |
| `pedido.creado` | That exact type |

The wildcard only goes at the end. `pedido.*.creado`, `pedido.cre*` and `*.*` are not patterns.

An endpoint declares the types it receives with a list of patterns. It receives an event if any
of them matches. Without a list, it receives all of them; with an empty list, none.

A type or a pattern that does not meet the grammar is an error of the integrator, not an event
that does not match: it is rejected when it is configured.

The type is part of the content of the message, not of its signature or of its headers: where it
goes in the payload is decided by the sender.

## 9. Conformance vectors

Each file in `vectors/` has the form described by
[`schemas/vector.schema.json`](schemas/vector.schema.json): `spec`, `id`, `kind` and `cases`. The
`kind` field says what is being tested and which fields each case carries.

The vectors are generated by `tools/gen_vectors.py`, which is an implementation separate from this
document and does not import any of the packages. All the secrets that appear in the vectors are
synthetic.
