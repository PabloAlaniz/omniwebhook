import { propagation, SpanKind, SpanStatusCode, trace } from '@opentelemetry/api';
import { W3CTraceContextPropagator } from '@opentelemetry/core';
import {
  AggregationTemporality,
  InMemoryMetricExporter,
  MeterProvider,
  PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics';
import {
  BasicTracerProvider,
  InMemorySpanExporter,
  SimpleSpanProcessor,
} from '@opentelemetry/sdk-trace-base';
import { beforeAll, describe, expect, it } from 'vitest';
import {
  type AttemptRecord,
  createReceiver,
  MemoryDeliveryLedger,
  MemoryIdempotencyStore,
  SendWebhook,
  type TransportRequest,
  type TransportResponse,
} from '../../src/index';
import { otelDeliveryLedger, otelReceptionObserver, otelTransport } from '../../src/otel';
import { standardSigner } from '../../src/standard';

const NOW = 1_700_000_000;
const SECRET = 'whsec_b21uaXdlYmhvb2stc2VjcmV0by1zaW50ZXRpY28tMDE=';

beforeAll(() => {
  propagation.setGlobalPropagator(new W3CTraceContextPropagator());
});

function metrics() {
  const reader = new PeriodicExportingMetricReader({
    exporter: new InMemoryMetricExporter(AggregationTemporality.CUMULATIVE),
    exportIntervalMillis: 3_600_000,
  });
  const provider = new MeterProvider({ readers: [reader] });
  /** Los puntos de una métrica: sus atributos y su valor (la cuenta, en un histograma). */
  async function points(name: string) {
    const { resourceMetrics } = await reader.collect();
    const metric = resourceMetrics.scopeMetrics
      .flatMap((scope) => scope.metrics)
      .find((each) => each.descriptor.name === name);
    return {
      unit: metric?.descriptor.unit,
      points: (metric?.dataPoints ?? []).map((point) => ({
        attributes: point.attributes,
        value:
          typeof point.value === 'number' ? point.value : (point.value as { count: number }).count,
        sum: typeof point.value === 'number' ? undefined : (point.value as { sum?: number }).sum,
      })),
    };
  }
  return { meter: provider.getMeter('prueba'), points };
}

function tracing() {
  const exporter = new InMemorySpanExporter();
  const provider = new BasicTracerProvider({ spanProcessors: [new SimpleSpanProcessor(exporter)] });
  return { tracer: provider.getTracer('prueba'), exporter };
}

describe('otelReceptionObserver', () => {
  it('cuenta las recepciones por resultado y mide su duración en segundos', async () => {
    const { meter, points } = metrics();
    let ms = 0;
    const receive = createReceiver({
      verifier: { verify: async () => ({ outcome: 'ok', eventKey: 'prueba:1', timestamp: null }) },
      store: new MemoryIdempotencyStore(),
      observer: otelReceptionObserver({ meter }),
      timer: { nowMs: () => (ms += 250) },
    });
    const request = { headers: [], query: [], body: new Uint8Array() };

    await receive.execute(request, () => {});
    await receive.execute(request, () => {});
    await receive.execute(request, () => {});

    const receptions = await points('omniwebhook.receptions');
    expect(receptions.unit).toBe('{reception}');
    expect(receptions.points).toEqual(
      expect.arrayContaining([
        { attributes: { 'omniwebhook.reception.outcome': 'ok' }, value: 1, sum: undefined },
        { attributes: { 'omniwebhook.reception.outcome': 'duplicate' }, value: 2, sum: undefined },
      ]),
    );
    const duration = await points('omniwebhook.reception.duration');
    expect(duration.unit).toBe('s');
    expect(
      duration.points.find((p) => p.attributes['omniwebhook.reception.outcome'] === 'ok'),
    ).toEqual({ attributes: { 'omniwebhook.reception.outcome': 'ok' }, value: 1, sum: 0.25 });
  });
});

const attempt = (overrides: Partial<AttemptRecord> = {}): AttemptRecord => ({
  messageId: 'msg_1',
  endpointId: 'ep_1',
  attempt: 1,
  at: NOW,
  deliveryClass: 'delivered',
  state: 'delivered',
  status: 200,
  problem: null,
  durationMs: 40,
  nextAt: null,
  ...overrides,
});

describe('otelDeliveryLedger', () => {
  it('guarda cada intento en el registro de adentro y lo cuenta por clase y estado', async () => {
    const { meter, points } = metrics();
    const inner = new MemoryDeliveryLedger();
    const ledger = otelDeliveryLedger(inner, { meter });

    await ledger.record(attempt());
    await ledger.record(
      attempt({ deliveryClass: 'retryable', state: 'pending', status: 503, nextAt: NOW + 5 }),
    );
    await ledger.record(
      attempt({ deliveryClass: 'blocked', state: 'blocked', status: null, durationMs: 0 }),
    );

    expect(inner.attempts()).toHaveLength(3);
    const attempts = await points('omniwebhook.delivery.attempts');
    expect(attempts.unit).toBe('{attempt}');
    expect(attempts.points).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          attributes: {
            'omniwebhook.delivery.class': 'delivered',
            'omniwebhook.delivery.state': 'delivered',
            'http.response.status_code': 200,
          },
          value: 1,
        }),
        expect.objectContaining({
          attributes: {
            'omniwebhook.delivery.class': 'blocked',
            'omniwebhook.delivery.state': 'blocked',
          },
          value: 1,
        }),
      ]),
    );
    const duration = await points('omniwebhook.delivery.attempt.duration');
    expect(duration.unit).toBe('s');
    expect(duration.points.map((p) => p.sum)).toEqual(expect.arrayContaining([0.04, 0]));
  });

  it('no pone el destino ni el mensaje como atributos', async () => {
    const { meter, points } = metrics();

    await otelDeliveryLedger(new MemoryDeliveryLedger(), { meter }).record(attempt());

    const text = JSON.stringify((await points('omniwebhook.delivery.attempts')).points);
    expect(text).not.toContain('ep_1');
    expect(text).not.toContain('msg_1');
  });

  it('si el registro de adentro falla, no cuenta el intento', async () => {
    const { meter, points } = metrics();
    const ledger = otelDeliveryLedger(
      {
        record: async () => {
          throw new Error('sin base de datos');
        },
      },
      { meter },
    );

    await expect(ledger.record(attempt())).rejects.toThrow('sin base de datos');
    expect((await points('omniwebhook.delivery.attempts')).points).toEqual([]);
  });

  it('sirve como fuente de la salud de los destinos si el de adentro lo es', async () => {
    const { meter } = metrics();
    const ledger = otelDeliveryLedger(new MemoryDeliveryLedger(), { meter });
    await ledger.record(attempt({ deliveryClass: 'gone', state: 'gone', status: 410 }));

    expect(await ledger.failuresOf('ep_1', 0)).toEqual({
      failures: 1,
      failingSince: NOW,
      gone: true,
    });
    await expect(
      otelDeliveryLedger({ record: async () => {} }, { meter }).failuresOf('ep_1', 0),
    ).rejects.toThrow(/resumen de fallos/);
  });
});

describe('otelTransport', () => {
  const request: TransportRequest = {
    url: 'https://hooks.ejemplo.test/entrada/token-secreto?clave=1',
    address: '93.184.216.34',
    headers: { 'webhook-id': 'msg_1', 'webhook-signature': 'v1,firma-secreta' },
    body: new TextEncoder().encode('{"dato":"privado"}'),
    timeoutSeconds: 20,
  };

  async function traced(response: TransportResponse | Error, url = request.url) {
    const { tracer, exporter } = tracing();
    const sent: TransportRequest[] = [];
    const transport = otelTransport(
      {
        post: async (each) => {
          sent.push(each);
          if (response instanceof Error) throw response;
          return response;
        },
      },
      { tracer },
    );
    const result = await transport.post({ ...request, url }).catch((error: unknown) => error);
    const [span] = exporter.getFinishedSpans();
    if (span === undefined || sent[0] === undefined) throw new Error('no hubo tramo');
    return { result, span, sent: sent[0] };
  }

  it('una entrega es un tramo de cliente HTTP sin error', async () => {
    const { result, span } = await traced({ status: 200, retryAfter: null });

    expect(result).toEqual({ status: 200, retryAfter: null });
    expect(span.name).toBe('POST');
    expect(span.kind).toBe(SpanKind.CLIENT);
    expect(span.attributes).toEqual({
      'http.request.method': 'POST',
      'server.address': 'hooks.ejemplo.test',
      'server.port': 443,
      'url.scheme': 'https',
      'omniwebhook.message.id': 'msg_1',
      'http.response.status_code': 200,
    });
    expect(span.status.code).toBe(SpanStatusCode.UNSET);
  });

  it('el tramo no lleva la URL completa, el cuerpo ni la firma', async () => {
    const { span } = await traced({ status: 200, retryAfter: null });

    const text = JSON.stringify([span.name, span.attributes, span.events]);
    for (const secret of ['token-secreto', 'clave=1', 'firma-secreta', 'privado']) {
      expect(text).not.toContain(secret);
    }
  });

  it('manda traceparent con el identificador del tramo, sin tocar las otras cabeceras', async () => {
    const { span, sent } = await traced({ status: 200, retryAfter: null });
    const { traceId, spanId } = span.spanContext();

    // Las banderas del final dependen de la versión del SDK; lo que importa es que esté muestreado.
    expect(sent.headers.traceparent).toMatch(new RegExp(`^00-${traceId}-${spanId}-0[13]$`));
    expect(sent.headers).toMatchObject(request.headers);
    expect(sent.body).toBe(request.body);
    expect(request.headers).not.toHaveProperty('traceparent');
  });

  it('el tramo es hijo de la operación que estaba activa', async () => {
    const { tracer, exporter } = tracing();
    const transport = otelTransport(
      { post: async () => ({ status: 200, retryAfter: null }) },
      { tracer },
    );
    // Sin gestor de contexto global, el tramo padre se pasa a mano: alcanza para comprobar
    // que el transporte toma el contexto activo.
    const { context, ROOT_CONTEXT } = await import('@opentelemetry/api');
    const { AsyncLocalStorage } = await import('node:async_hooks');
    const storage = new AsyncLocalStorage<typeof ROOT_CONTEXT>();
    context.setGlobalContextManager({
      active: () => storage.getStore() ?? ROOT_CONTEXT,
      with: (ctx, fn, thisArg, ...args) => storage.run(ctx, () => fn.call(thisArg, ...args)),
      bind: (_ctx, target) => target,
      enable() {
        return this;
      },
      disable() {
        return this;
      },
    });
    const parent = tracer.startSpan('registrar pedido');

    await context.with(trace.setSpan(context.active(), parent), () => transport.post(request));
    parent.end();
    context.disable();

    const child = exporter.getFinishedSpans().find((span) => span.name === 'POST');
    expect(child?.spanContext().traceId).toBe(parent.spanContext().traceId);
    expect(child?.parentSpanContext?.spanId).toBe(parent.spanContext().spanId);
  });

  it.each([
    [{ status: 503, retryAfter: null }, '503', 503],
    [{ status: 404, retryAfter: null }, '404', 404],
    [{ failure: 'timeout' }, 'timeout', undefined],
    [{ failure: 'network' }, 'network', undefined],
  ] as const)(
    'un intento que falla (%j) marca el tramo con error',
    async (response, type, status) => {
      const { span } = await traced(response);

      expect(span.attributes['error.type']).toBe(type);
      expect(span.attributes['http.response.status_code']).toBe(status);
      expect(span.status.code).toBe(SpanStatusCode.ERROR);
    },
  );

  it('una redirección no es un error del tramo', async () => {
    const { span } = await traced({ status: 302, retryAfter: null });

    expect(span.status.code).toBe(SpanStatusCode.UNSET);
  });

  it('si el transporte lanza, el tramo se cierra con error y la excepción sigue su camino', async () => {
    const { result, span } = await traced(new TypeError('fallo interno'));

    expect(result).toBeInstanceOf(TypeError);
    expect(span.attributes['error.type']).toBe('TypeError');
    expect(span.ended).toBe(true);
  });

  it('con una URL que la plataforma no interpreta, el tramo no lleva datos del destino', async () => {
    const { span } = await traced({ failure: 'network' }, 'https://destino con espacio.test/');

    expect(span.attributes).not.toHaveProperty('server.address');
  });

  it('el puerto es el de la URL si lo trae, y el del esquema si no', async () => {
    expect(
      (await traced({ status: 200, retryAfter: null }, 'http://a.test/')).span.attributes,
    ).toMatchObject({ 'server.port': 80, 'url.scheme': 'http' });
    expect(
      (await traced({ status: 200, retryAfter: null }, 'https://a.test:8443/')).span.attributes,
    ).toMatchObject({ 'server.port': 8443 });
  });

  it('de punta a punta: un intento de SendWebhook deja un tramo y una métrica', async () => {
    const { tracer, exporter } = tracing();
    const { meter, points } = metrics();
    const send = new SendWebhook({
      signer: standardSigner({ secrets: [SECRET] }),
      transport: otelTransport(
        { post: async () => ({ status: 200, retryAfter: null }) },
        { tracer },
      ),
      resolver: { resolve: async () => ['93.184.216.34'] },
      ledger: otelDeliveryLedger(new MemoryDeliveryLedger(), { meter }),
      clock: { now: () => NOW },
      timer: { nowMs: () => 0 },
      random: { next: () => 0 },
    });

    await send.execute({
      endpoint: { id: 'ep_1', url: 'https://hooks.ejemplo.test/entrada' },
      message: { id: 'msg_9', payload: new Uint8Array([123, 125]) },
      attempt: 1,
    });

    expect(exporter.getFinishedSpans()[0]?.attributes['omniwebhook.message.id']).toBe('msg_9');
    expect((await points('omniwebhook.delivery.attempts')).points).toHaveLength(1);
  });
});
