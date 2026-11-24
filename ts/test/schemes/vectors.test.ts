import {
  creemScheme,
  githubScheme,
  type HmacBodyOptions,
  hmacBodyScheme,
  mercadoPagoScheme,
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
