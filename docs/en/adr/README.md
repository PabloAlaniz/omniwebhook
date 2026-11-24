# Architecture decisions

> **Translation.** This is a translation of the [Spanish original](../../adr/README.md). If the two disagree, the Spanish text wins.

Every design decision that constrains the rest is written down here, in a numbered file. A
decision is not edited to change it: another one that replaces it is added, and the status of the
previous one is updated.

| No. | Decision | Status |
|---|---|---|
| [0001](0001-arquitectura-en-capas.md) | Layered architecture with inward-pointing dependencies | Accepted |
| [0002](0002-formato-de-salida-estandar.md) | Standard outgoing format, with the reference library behind a port | Accepted |
| [0003](0003-forma-de-la-url-de-destino.md) | The form of the destination URL is checked with a grammar of our own | Accepted |
| [0004](0004-variantes-sincronica-y-asincronica.md) | In Python, every piece with input/output has a synchronous and an asynchronous variant | Accepted |
| [0005](0005-redes-permitidas.md) | Explicit allowed networks, never enabling cloud metadata | Accepted |
| [0006](0006-dns-sobre-https.md) | DNS over HTTPS for environments without system DNS | Accepted |
| [0007](0007-firma-asimetrica.md) | Asymmetric signature: a separate scheme and an optional dependency | Accepted |
| [0008](0008-almacen-clave-valor.md) | One store on top of any key-value store, with the guarantee in plain sight | Accepted |
| [0009](0009-bandeja-de-salida.md) | An outbox and the dispatch of a batch, without a scheduler | Accepted |
| [0010](0010-firma-asimetrica-al-emitir.md) | Signing with a private key: the endpoint goes into the message and the key does not leave the sender | Accepted |
