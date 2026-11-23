import {
  creemScheme,
  githubScheme,
  type HmacBodyOptions,
  hmacBodyScheme,
  mercadoPagoScheme,
  stripeScheme,
  tiktokScheme,
} from '../../src/index';
import { standardScheme } from '../../src/standard';
import { describeVerifyVectors, toleranceOf } from '../support/verify-vectors';

describeVerifyVectors('standard', (c, clock) =>
  standardScheme({ secrets: c.secrets, clock, ...toleranceOf(c) }),
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
