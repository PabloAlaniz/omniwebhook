import { lookup as systemLookup } from 'node:dns/promises';
import type { DnsResolver } from '../../application/ports';

type Lookup = (host: string) => Promise<ReadonlyArray<{ address: string }>>;

export interface NodeDnsResolverOptions {
  /** Devuelve todas las direcciones de un nombre. Por defecto, pregunta al sistema. */
  readonly lookup?: Lookup;
}

/** Resuelve nombres con el sistema operativo. Un nombre que no existe da una lista vacía. */
export function nodeDnsResolver(options: NodeDnsResolverOptions = {}): DnsResolver {
  const lookup = options.lookup ?? ((host: string) => systemLookup(host, { all: true }));

  return {
    async resolve(host: string): Promise<readonly string[]> {
      try {
        const found = await lookup(host);
        return found.map((entry) => entry.address);
      } catch (error) {
        if ((error as { code?: unknown }).code === 'ENOTFOUND') return [];
        throw error;
      }
    },
  };
}
