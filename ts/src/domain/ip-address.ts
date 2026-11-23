import { ConfigurationError } from './errors';

/** Una dirección IP como bytes: 4 para IPv4, 16 para IPv6. */
type AddressBytes = readonly number[];

const DECIMAL_OCTET = /^(0|[1-9][0-9]{0,2})$/;
const HEX_GROUP = /^[0-9a-fA-F]{1,4}$/;

function parseIPv4(text: string): AddressBytes | null {
  const parts = text.split('.');
  if (parts.length !== 4) return null;
  const bytes: number[] = [];
  for (const part of parts) {
    if (!DECIMAL_OCTET.test(part)) return null;
    const value = Number(part);
    if (value > 255) return null;
    bytes.push(value);
  }
  return bytes;
}

/** Los grupos de 16 bits de un tramo como `2001:db8` o `ffff:10.0.0.1`. */
function parseGroups(text: string): number[] | null {
  if (text === '') return [];
  const parts = text.split(':');
  const groups: number[] = [];
  for (const [index, part] of parts.entries()) {
    if (part.includes('.')) {
      // Una IPv4 embebida sólo puede ir al final y ocupa dos grupos.
      const ipv4 = index === parts.length - 1 ? parseIPv4(part) : null;
      if (ipv4 === null) return null;
      const [a = 0, b = 0, c = 0, d = 0] = ipv4;
      groups.push((a << 8) | b, (c << 8) | d);
    } else {
      if (!HEX_GROUP.test(part)) return null;
      groups.push(Number.parseInt(part, 16));
    }
  }
  return groups;
}

function parseIPv6(text: string): AddressBytes | null {
  const halves = text.split('::');
  if (halves.length > 2) return null;

  const head = parseGroups(halves[0] ?? '');
  const tail = halves.length === 2 ? parseGroups(halves[1] ?? '') : [];
  if (head === null || tail === null) return null;
  // Una IPv4 embebida tiene que quedar en los últimos 32 bits.
  if (halves.length === 2 && (halves[0] ?? '').includes('.')) return null;

  const present = head.length + tail.length;
  if (halves.length === 1 ? present !== 8 : present > 7) return null;

  const groups = [...head, ...new Array<number>(8 - present).fill(0), ...tail];
  return groups.flatMap((group) => [group >> 8, group & 0xff]);
}

function parseAddress(text: string): AddressBytes | null {
  return text.includes(':') ? parseIPv6(text) : parseIPv4(text);
}

interface Network {
  readonly bytes: AddressBytes;
  readonly prefix: number;
}

function network(cidr: string): Network {
  const [address = '', prefix = ''] = cidr.split('/');
  const bytes = parseAddress(address);
  if (bytes === null) throw new Error(`rango inválido: ${cidr}`);
  return { bytes, prefix: Number(prefix) };
}

function contains(net: Network, address: AddressBytes): boolean {
  if (net.bytes.length !== address.length) return false;
  for (let bit = 0; bit < net.prefix; bit += 8) {
    const index = bit / 8;
    const remaining = net.prefix - bit;
    const mask = remaining >= 8 ? 0xff : (0xff << (8 - remaining)) & 0xff;
    if (((net.bytes[index] ?? 0) & mask) !== ((address[index] ?? 0) & mask)) return false;
  }
  return true;
}

/** Los rangos a los que nunca se entrega (sección 8.1). */
const BLOCKED: readonly Network[] = [
  '0.0.0.0/8',
  '10.0.0.0/8',
  '100.64.0.0/10',
  '127.0.0.0/8',
  '169.254.0.0/16',
  '172.16.0.0/12',
  '192.0.0.0/24',
  '192.0.2.0/24',
  '192.168.0.0/16',
  '198.18.0.0/15',
  '198.51.100.0/24',
  '203.0.113.0/24',
  '224.0.0.0/4',
  '240.0.0.0/4',
  '::/128',
  '::1/128',
  '64:ff9b::/96',
  '100::/64',
  '2001:db8::/32',
  'fc00::/7',
  'fe80::/10',
  'ff00::/8',
].map(network);

const IPV4_MAPPED = network('::ffff:0:0/96');

/** Los servicios de metadatos de las nubes: ninguna red permitida los habilita (sección 8.1). */
const NEVER_ALLOWED: readonly Network[] = [
  '169.254.0.0/16',
  '100.100.100.200/32',
  'fd00:ec2::254/128',
].map(network);

const PREFIX = /^(0|[1-9][0-9]{0,2})$/;

/** Las redes a las que se permite entregar aunque estén en un rango bloqueado. */
export type AllowedNetworks = readonly Network[];

/** Una red con la forma `dirección/prefijo` de la sección 8.1, o `null` si no la tiene. */
function parseNetwork(text: string): Network | null {
  const slash = text.indexOf('/');
  if (slash === -1) return null;
  const prefixText = text.slice(slash + 1);
  const bytes = parseAddress(text.slice(0, slash));
  if (bytes === null || !PREFIX.test(prefixText)) return null;
  const prefix = Number(prefixText);
  if (prefix > bytes.length * 8) return null;
  // Los bits fuera del prefijo tienen que ser cero.
  const net = { bytes, prefix };
  const masked = bytes.map((byte, index) => {
    const remaining = prefix - index * 8;
    if (remaining >= 8) return byte;
    if (remaining <= 0) return 0;
    return byte & ((0xff << (8 - remaining)) & 0xff);
  });
  if (masked.some((byte, index) => byte !== bytes[index])) return null;
  // Las IPv6 que envuelven una IPv4 se evalúan por la IPv4: una red así nunca coincidiría.
  if (prefix >= 96 && contains(IPV4_MAPPED, bytes)) return null;
  return net;
}

/**
 * Lee la lista de redes permitidas. Una red que no tiene la forma `dirección/prefijo` de la
 * sección 8.1 es un error de configuración.
 */
export function allowedNetworks(cidrs: readonly string[]): AllowedNetworks {
  return cidrs.map((cidr) => {
    const net = parseNetwork(cidr);
    if (net === null) throw new ConfigurationError(`red permitida inválida: ${cidr}`);
    return net;
  });
}

/** Si el texto es una dirección IP literal. */
export function isIpAddress(text: string): boolean {
  return parseAddress(text) !== null;
}

/**
 * Si no se puede entregar a esta dirección: no es una dirección IP, o está en un rango
 * bloqueado y fuera de las redes permitidas. Una IPv6 que envuelve una IPv4 se evalúa por
 * la IPv4 que contiene.
 */
export function isBlockedAddress(text: string, allowed: AllowedNetworks = []): boolean {
  const parsed = parseAddress(text);
  if (parsed === null) return true;
  const address = contains(IPV4_MAPPED, parsed) ? parsed.slice(12) : parsed;
  const inside = (net: Network) => contains(net, address);
  if (NEVER_ALLOWED.some(inside)) return true;
  return BLOCKED.some(inside) && !allowed.some(inside);
}
