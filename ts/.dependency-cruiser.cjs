/**
 * Reglas de arquitectura. Las dependencias apuntan hacia adentro:
 *
 *   entrypoints → adapters → application → domain
 *
 * Ver docs/adr/0001-arquitectura-en-capas.md y docs/adr/0002-formato-de-salida-estandar.md.
 */
module.exports = {
  forbidden: [
    {
      name: 'sin-ciclos',
      comment: 'Un ciclo entre módulos esconde una responsabilidad mal repartida.',
      severity: 'error',
      from: {},
      to: { circular: true },
    },
    {
      name: 'dominio-puro',
      comment:
        'El dominio son reglas puras: no importa otras capas, ni módulos de la plataforma, ni paquetes.',
      severity: 'error',
      from: { path: '^src/domain/' },
      to: { pathNot: '^src/domain/' },
    },
    {
      name: 'aplicacion-hacia-adentro',
      comment:
        'Los casos de uso conocen el dominio y sus propios puertos; todo lo demás llega inyectado.',
      severity: 'error',
      from: { path: '^src/application/' },
      to: { pathNot: '^src/(domain|application)/' },
    },
    {
      name: 'adaptadores-sin-entradas',
      comment: 'Un adaptador no depende de un punto de entrada.',
      severity: 'error',
      from: { path: '^src/adapters/' },
      to: { path: '^src/entrypoints/' },
    },
    {
      name: 'libreria-del-formato-estandar-aislada',
      comment:
        'Sólo el adaptador del esquema estándar puede importar la librería de referencia: así se puede reemplazar sin tocar nada más.',
      severity: 'error',
      from: { pathNot: '^src/adapters/schemes/standard/' },
      to: { path: 'standardwebhooks' },
    },
    {
      name: 'sin-imports-rotos',
      severity: 'error',
      from: {},
      to: { couldNotResolve: true },
    },
  ],
  options: {
    doNotFollow: { path: 'node_modules' },
    tsPreCompilationDeps: true,
    tsConfig: { fileName: 'tsconfig.json' },
  },
};
