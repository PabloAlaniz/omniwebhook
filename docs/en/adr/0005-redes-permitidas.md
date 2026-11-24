# 0005. Explicit allowed networks, never enabling cloud metadata

> **Translation.** This is a translation of the [Spanish original](../../adr/0005-redes-permitidas.md). If the two disagree, the Spanish text wins.

- Status: accepted
- Date: 2026-11-23

## Context

The URL policy blocks private, local and reserved ranges. That is the right thing when endpoints
are registered by third parties, but it leaves out a common case: a product installed by its own
user (self-hosted) that has to deliver to services on the same machine or the same local network,
such as an automation tool in another container.

Without an option in the package, the integrator has two bad ways out: a fake resolver that hides
the real addresses, or a transport that ignores the validated address. Both switch off the whole
policy, not only for the network that was needed.

## Decision

1. The sender's configuration accepts a list of allowed networks, empty by default. A blocked
   address that falls within a network on the list is accepted.
2. Networks are written `dirección/prefijo` in a strict form: the same address grammar as in section
   8.1, a decimal prefix with no leading zeros and the bits outside the prefix set to zero. A
   badly written network is a configuration error at construction time, not a rejection on every
   attempt.
3. The clouds' metadata services (`169.254.0.0/16`, `100.100.100.200/32`,
   `fd00:ec2::254/128`) are never allowed. They are the most valuable target of an attack of this
   kind and no legitimate use of a webhook needs them.
4. An IPv6 address that wraps an IPv4 address is still evaluated by the IPv4 address, and an IPv6
   network inside `::ffff:0:0/96` is not accepted, because it would never match.

## Consequences

- A self-hosted installation can deliver to its network without disabling the rest of the policy:
  the form of the URL, the credentials, the URL scheme and the connection to the validated address stay
  the same.
- Allowing `0.0.0.0/0` is possible and is the responsibility of whoever configures it; cloud
  metadata stays blocked all the same.
- The list of addresses that are never allowed is part of the specification: adding one is a change
  to the specification, with its vectors.
