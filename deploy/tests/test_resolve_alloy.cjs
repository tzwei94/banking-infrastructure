const { test } = require('node:test');
const assert = require('node:assert/strict');
const { selectRun, resolveImage } = require('../scripts/resolve-alloy.cjs');
const repository = '123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/banking-dev/banking-alloy';
const digest = repository + '@sha256:' + 'a'.repeat(64);
const run = { id: 42, run_attempt: 2, head_sha: 'b'.repeat(40) };
const manifest = { schema_version: 1, alloy_image: digest, repository: 'owner/deployment', run_id: 42, run_attempt: 2, alloy_source_sha: run.head_sha };
const context = { repo: { owner: 'owner', repo: 'deployment' } };
test('selects successful main publication and exact attempt artifact', async () => {
  const selected = await selectRun({ rest: { actions: { listWorkflowRuns: async args => {
    assert.equal(args.workflow_id, 'publish-alloy.yml');
    assert.equal(args.branch, 'main');
    assert.equal(args.status, 'success');
    return { data: { workflow_runs: [run] } };
  } } } }, context);
  assert.equal(selected.artifact, 'alloy-image-manifest-42-2');
  assert.equal(selected.id, 42);
});
test('no successful publication fails clearly', async () => {
  await assert.rejects(selectRun({ rest: { actions: { listWorkflowRuns: async () => ({ data: { workflow_runs: [] } }) } } }, context), /No successful/);
});
test('explicit digest overrides manifest', () => {
  assert.equal(resolveImage(digest, repository), digest);
});
test('valid manifest resolves digest', () => {
  assert.equal(resolveImage('', repository, manifest, run, 'owner/deployment'), digest);
});
test('rejects bad digest and wrong repository', () => {
  for (const image of [repository + ':latest', 'other/image@sha256:' + 'a'.repeat(64), digest + '\nextra', digest + '\n']) {
    assert.throws(() => resolveImage(image, repository));
  }
});
test('rejects missing manifest and mismatched provenance', () => {
  assert.throws(() => resolveImage('', repository));
  for (const change of [{ schema_version: 2 }, { repository: 'other/repo' }, { run_id: 41 }, { run_attempt: 1 }, { alloy_source_sha: 'c'.repeat(40) }, { alloy_image: 'bad' }]) {
    assert.throws(() => resolveImage('', repository, { ...manifest, ...change }, run, 'owner/deployment'));
  }
});
