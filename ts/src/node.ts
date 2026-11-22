/**
 * Adaptadores que necesitan los módulos de red de Node. Viven en una entrada aparte
 * para que la entrada principal siga funcionando en entornos sin ellos.
 */
import { nodeDnsResolver } from './adapters/dns/node';
import { nodeTransport } from './adapters/transport/node';
import type { DnsResolver } from './application/ports';
import type { SendWebhook } from './application/send-webhook';
import { createSender, type SenderOptions } from './entrypoints/sender';

export { type NodeDnsResolverOptions, nodeDnsResolver } from './adapters/dns/node';
export { nodeTransport } from './adapters/transport/node';

export interface NodeSenderOptions extends Omit<SenderOptions, 'resolver'> {
  readonly resolver?: DnsResolver;
}

/** Arma el caso de uso de envío para Node: resuelve con el sistema y fija la dirección validada. */
export function createNodeSender(options: NodeSenderOptions): SendWebhook {
  return createSender({
    ...options,
    transport: options.transport ?? nodeTransport(),
    resolver: options.resolver ?? nodeDnsResolver(),
  });
}
