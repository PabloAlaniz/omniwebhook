# How a version is published

> **Translation.** This is a translation of the [Spanish original](../publicar.md). If the two disagree, the Spanish text wins.

The two packages always carry the same version and are published together.

## The circuit

1. Every commit on `main` follows [Conventional Commits](https://www.conventionalcommits.org/en/).
2. The [`release.yml`](../../.github/workflows/release.yml) workflow keeps a pull request open
   with the next version and the CHANGELOG, computed from those commits.
3. Merging that pull request creates the tag and the release on GitHub.
4. The same workflow publishes to npm and to PyPI from that tag, after running the tests.

The version is written in a single place (`.release-please-manifest.json`) and the tool copies it to
`ts/package.json`, `python/pyproject.toml` and `python/uv.lock`.

## Trusted publishing

No publishing token is stored in the repository. Each registry checks, with a
short-lived credential issued by GitHub, that the one publishing is this workflow in this repository.

That is already configured. It is noted here in case it has to be redone:

| Where | What |
|---|---|
| GitHub, *Settings → Actions → General* | Allow GitHub Actions to create pull requests; without that, release-please cannot open the one for the version |
| GitHub, *Settings → Environments* | The `npm` and `pypi` environments, without manual approval |
| PyPI, *Publishing* | The trusted publisher of the `omniwebhook` project: this repository, workflow `release.yml`, environment `pypi` |
| npm, *omniwebhook → Settings → Trusted Publisher* | The trusted publisher: this repository, workflow `release.yml`, environment `npm`, with **Allow npm publish** checked |

npm details that are not obvious:

- The trusted publisher can only be configured on a package that already exists. That is why
  0.1.0 was published by hand from `ts/` and only 0.1.1 came out of the workflow.
- If **Allow npm publish** is not checked, the publisher can only do `npm stage publish`: the
  version is put on hold until it is approved by hand with 2FA, and the workflow's `npm publish` fails.
- A new publisher stays *Pending validation* and expires if the workflow does not publish within about two days.
  Validating it requires a new version; re-running the job of an already published version
  does not work.

The first version starts at 0.1.0 because of `initial-version` in `release-please-config.json`; without that,
release-please proposes 1.0.0.

## What accompanies each version

- **Provenance.** npm publishes with `--provenance` and PyPI with attestations: each registry keeps
  the proof that the package came from this repository, from this workflow and from which commit.
- **Dependency inventory.** The `sbom` job attaches to the release on GitHub one SBOM in SPDX
  format per package. Publishing does not depend on it: if it fails, the packages go out anyway.
- **The version number inside the code.** `PACKAGE_VERSION` lives in
  `ts/src/domain/package-version.ts` and in `python/src/omniwebhook/domain/package_version.py`, and
  it is what goes in the `user-agent` header. Release-please updates it together with the manifests,
  and a test in each package fails if they do not match.

## If something goes wrong

A published version cannot be replaced. If one package was published and the other was not, the
cause is fixed and only the job that failed is re-run. If the published version has an error, a
new one is published; the previous one is not deleted.
