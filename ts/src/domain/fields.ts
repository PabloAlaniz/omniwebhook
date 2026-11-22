type Groups<K extends string> = Readonly<Record<K, readonly string[]>>;

export type Singles<R extends string, O extends string> = { readonly [K in R]: string } & {
  readonly [K in O]: string | undefined;
};

/**
 * Reduce cada campo a su único valor, en el orden de la sección 4.1: primero se
 * informa lo que falta y después lo repetido. Nunca elige entre valores repetidos.
 */
export function pickSingles<R extends string, O extends string = never>(
  required: Groups<R>,
  optional?: Groups<O>,
): Singles<R, O> | 'missing' | 'ambiguous' {
  const requiredGroups = Object.entries<readonly string[]>(required);
  const allGroups = [...requiredGroups, ...Object.entries<readonly string[]>(optional ?? {})];

  if (requiredGroups.some(([, values]) => values.length === 0)) return 'missing';
  if (allGroups.some(([, values]) => values.length > 1)) return 'ambiguous';

  return Object.fromEntries(allGroups.map(([name, values]) => [name, values[0]])) as Singles<R, O>;
}
