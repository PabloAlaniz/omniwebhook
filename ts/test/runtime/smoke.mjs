// Prueba de humo para los entornos con API Fetch que no son Node.
//
// No usa ningún framework de tests ni módulos de Node: sólo el paquete ya compilado y las
// APIs web. Recorre un ciclo completo —firmar, entregar, recibir, repetir— para comprobar
// que la entrada principal y `omniwebhook/standard` cargan y funcionan en cada entorno.
//
// Uso, después de `pnpm build`:  node | deno run | bun  test/runtime/smoke.mjs

import {
  createReceiver,
  createSender,
  fetchTransport,
  githubScheme,
  MemoryDeliveryLedger,
  MemoryIdempotencyStore,
  randomMessageId,
  toIncomingRequest,
  toResponse,
  USER_AGENT,
} from '../../dist/index.js';
import { standardScheme, standardSigner } from '../../dist/standard.js';

const SECRET = 'whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE=';
const URL_DESTINO = 'https://hooks.ejemplo.test/entrada';

function check(what, actual, expected) {
  if (actual !== expected) {
    throw new Error(
      `${what}: se esperaba ${JSON.stringify(expected)}, hubo ${JSON.stringify(actual)}`,
    );
  }
}

// --- Emitir: lo que sale se captura en lugar de mandarse a la red ---------------------
let outgoing;
const send = createSender({
  signer: standardSigner({ secrets: [SECRET] }),
  ledger: new MemoryDeliveryLedger(),
  resolver: { resolve: async () => ['93.184.216.34'] },
  transport: fetchTransport({
    fetch: async (url, init) => {
      outgoing = new Request(url, init);
      return new Response('un cuerpo que no se lee', { status: 200 });
    },
  }),
});
const payload = new TextEncoder().encode('{"type":"pedido.creado","data":{"id":42}}');
const attempt = await send.execute({
  endpoint: { id: 'ep_1', url: URL_DESTINO },
  message: { id: randomMessageId(), payload },
  attempt: 1,
});
check('estado de la entrega', attempt.state, 'delivered');
check('user-agent', outgoing.headers.get('user-agent'), USER_AGENT);

// --- Recibir: el mismo pedido, una vez y repetido -------------------------------------
const receive = createReceiver({
  verifier: standardScheme({ secrets: [SECRET] }),
  store: new MemoryIdempotencyStore(),
});
let processed = 0;
const handle = async (request) =>
  toResponse(
    await receive.execute(await toIncomingRequest(request), () => {
      processed += 1;
    }),
  );

check('primera recepción', (await handle(outgoing.clone())).status, 200);
check('recepción repetida', (await handle(outgoing.clone())).status, 200);
check('veces que se procesó', processed, 1);

const tampered = new Request(URL_DESTINO, {
  method: 'POST',
  headers: outgoing.headers,
  body: '{"type":"pedido.creado","data":{"id":43}}',
});
check('cuerpo alterado', (await handle(tampered)).status, 401);

// --- Un esquema que no depende de la librería de referencia: sólo Web Crypto ----------
const key = await crypto.subtle.importKey(
  'raw',
  new TextEncoder().encode('secreto-sintetico'),
  { name: 'HMAC', hash: 'SHA-256' },
  false,
  ['sign'],
);
const mac = new Uint8Array(await crypto.subtle.sign('HMAC', key, payload));
const hex = [...mac].map((byte) => byte.toString(16).padStart(2, '0')).join('');
const verification = await githubScheme({ secrets: ['secreto-sintetico'] }).verify({
  headers: [
    ['x-hub-signature-256', `sha256=${hex}`],
    ['x-github-delivery', 'entrega-1'],
  ],
  query: [],
  body: payload,
});
check('esquema con Web Crypto', verification.outcome, 'ok');

console.log(`ok: ${USER_AGENT}`);
