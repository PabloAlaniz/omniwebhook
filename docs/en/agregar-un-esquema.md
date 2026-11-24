# How to add a signature scheme

> **Translation.** This is a translation of the [Spanish original](../agregar-un-esquema.md). If the two disagree, the Spanish text wins.

A scheme is an adapter: it knows how to read a sender's request, compute the signature that should
have arrived and say what the event key is. The order of the checks, the constant-time
comparison, secret rotation and freshness are already taken care of and are common to all of them.

Adding one does not touch the core. It goes in this order.

## 1. Write it in the specification

Add a section to [`spec/SPEC.en.md`](../../spec/SPEC.en.md), next to the other schemes, with the
sender's public documentation in front of you. It has to answer:

- which headers or parameters it requires and which are optional;
- how the secret is interpreted (text, base64, with a prefix);
- what exactly the signed content is;
- how the signature is encoded (hexadecimal or base64) and whether more than one can come;
- whether it carries a timestamp, in what unit and with how many digits at most;
- where the event key comes from, and what happens if that piece of data is missing.

If the sender signs only the body with HMAC-SHA256, a new scheme is probably not needed: the
generic `hmac-body` scheme already covers it with configuration.

## 2. Add the vectors

The vectors are generated with [`tools/gen_vectors.py`](../../tools/gen_vectors.py), which is a
separate implementation of the specification. Add:

- the verification of the scheme in the `check` function;
- a `verificar_<esquema>` function with the cases.

At a minimum: a valid signature; each required piece of data missing; each piece of data repeated;
each invalid form; a signature from another secret; the body altered; secret rotation; and, if it
carries a timestamp, the exact edge of the tolerance in each direction.

If the sender publishes an example with its signature, use it to check that the generator signs the same way.
All the secrets in the vectors are synthetic.

```bash
python3 tools/gen_vectors.py
```

## 3. Write the adapter in each package

With the vectors generated, the tests of both packages already fail. The adapter defines three things:

| What | What for |
|---|---|
| The secret's key | Convert the secret into the HMAC key, or say that it cannot be used |
| The reading | Extract from the request the timestamp, the signatures received and the event key; or return `missing`, `ambiguous` or `malformed` |
| The expected signature | Compute, for a key, the signature that should have arrived |

In TypeScript it is an object that is passed to `schemeVerifier`
([`ts/src/adapters/schemes/`](../../ts/src/adapters/schemes/)); in Python, a class that is passed to
`scheme_verifier` ([`python/src/omniwebhook/adapters/schemes/`](../../python/src/omniwebhook/adapters/schemes/)).
The Stripe scheme is the shortest example with a timestamp; the GitHub one, without it.

Rules worth following:

- Use the domain functions to pick a single value (`pickSingles`, `pick_singles`) and to
  split headers with pairs (`parsePairs`, `parse_pairs`). That way the order "first what is missing,
  then what is repeated" comes out by itself.
- The reading never throws because of the request: it returns one of the three rejections.
- The event key is computed only once the signature has turned out to be valid.
- In hexadecimal, lowercase the signature received. In base64, leave it as it arrived.

Afterwards, register the scheme in the vector tests of each package and export it in the public
entry point.

## 4. Check

```bash
pnpm check                      # TypeScript
cd python && uv run pytest      # Python
pnpm test:interop               # both give the same answer
```

Add the scheme to the list in `tools/interop.py` so that the random variations cover it
too, and to the table in the [guide to receiving](recibir.md).
