// Un receptor sobre node:http, sin framework.
import { createServer } from 'node:http';
import { createReceiver, MemoryIdempotencyStore, stripeScheme } from 'omniwebhook';
import { nodeIncomingRequest, writeNodeResponse } from 'omniwebhook/node';

const receive = createReceiver({
  verifier: stripeScheme({ secrets: [process.env.WEBHOOK_SECRET ?? ''] }),
  // En memoria sólo sirve con un proceso. En producción, un almacén compartido.
  store: new MemoryIdempotencyStore(),
});

const server = createServer(async (request, response) => {
  if (request.method !== 'POST' || !request.url?.startsWith('/webhooks')) {
    response.writeHead(404).end();
    return;
  }
  // Lee el cuerpo crudo: la firma se calcula sobre los bytes tal como llegaron.
  const reception = await receive.execute(await nodeIncomingRequest(request), (event) => {
    const payload = JSON.parse(new TextDecoder().decode(event.request.body));
    console.log(`procesado ${event.eventKey} ${payload.type}`);
  });
  writeNodeResponse(response, reception);
});

server.listen(Number(process.env.PORT ?? 3000), '127.0.0.1');
