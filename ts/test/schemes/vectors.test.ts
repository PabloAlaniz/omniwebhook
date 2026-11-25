import {
  creemScheme,
  discordScheme,
  githubScheme,
  googleChannelScheme,
  googlePubSubScheme,
  type HmacBodyOptions,
  hmacBodyScheme,
  mercadoPagoScheme,
  type SharedTokenOptions,
  sharedTokenScheme,
  shopifyScheme,
  slackScheme,
  stripeScheme,
  tiktokScheme,
} from '../../src/index';
import { standardPublicKeyScheme, standardScheme } from '../../src/standard';
import { describeVerifyVectors, toleranceOf } from '../support/verify-vectors';

describeVerifyVectors('standard', (c, clock) =>
  standardScheme({ secrets: c.secrets, clock, ...toleranceOf(c) }),
);
describeVerifyVectors('standard-v2a', (c, clock) =>
  standardPublicKeyScheme({
    publicKeys: c.secrets,
    endpointId: String(c.options?.endpoint_id),
    clock,
    ...toleranceOf(c),
  }),
);
describeVerifyVectors('stripe', (c, clock) =>
  stripeScheme({ secrets: c.secrets, clock, ...toleranceOf(c) }),
);
describeVerifyVectors('tiktok', (c, clock) =>
  tiktokScheme({ secrets: c.secrets, clock, ...toleranceOf(c) }),
);
describeVerifyVectors('mercadopago', (c, clock) =>
  mercadoPagoScheme({ secrets: c.secrets, clock, ...toleranceOf(c) }),
);
describeVerifyVectors('github', (c) => githubScheme({ secrets: c.secrets }));
describeVerifyVectors('creem', (c) => creemScheme({ secrets: c.secrets }));
describeVerifyVectors('discord', (c, clock) =>
  discordScheme({ publicKeys: c.secrets, clock, ...toleranceOf(c) }),
);
describeVerifyVectors('shopify', (c) => shopifyScheme({ secrets: c.secrets }));
describeVerifyVectors('slack', (c, clock) =>
  slackScheme({ secrets: c.secrets, clock, ...toleranceOf(c) }),
);
describeVerifyVectors('hmac-body', (c) => {
  const o = c.options as {
    header: string;
    prefix?: string;
    encoding?: 'hex' | 'base64';
    name?: string;
    id_header?: string;
  };
  const options: HmacBodyOptions = {
    secrets: c.secrets,
    header: o.header,
    ...(o.prefix === undefined ? {} : { prefix: o.prefix }),
    ...(o.encoding === undefined ? {} : { encoding: o.encoding }),
    ...(o.name === undefined ? {} : { name: o.name }),
    ...(o.id_header === undefined ? {} : { idHeader: o.id_header }),
  };
  return hmacBodyScheme(options);
});
describeVerifyVectors('shared-token', (c) => {
  const o = c.options as { header?: string; query?: string; name?: string; id_header?: string };
  const options: SharedTokenOptions = {
    secrets: c.secrets,
    ...(o.header === undefined ? {} : { header: o.header }),
    ...(o.query === undefined ? {} : { query: o.query }),
    ...(o.name === undefined ? {} : { name: o.name }),
    ...(o.id_header === undefined ? {} : { idHeader: o.id_header }),
  };
  return sharedTokenScheme(options);
});
describeVerifyVectors('google-channel', (c) => googleChannelScheme({ secrets: c.secrets }));
describeVerifyVectors('google-pubsub', (c) => {
  const query = c.options?.query;
  return googlePubSubScheme({
    secrets: c.secrets,
    ...(typeof query === 'string' ? { query } : {}),
  });
});
