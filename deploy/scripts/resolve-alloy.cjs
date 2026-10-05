// Resolve the collector independently from the application's source revision.
async function selectRun(github, context) {
  const { data } = await github.rest.actions.listWorkflowRuns({
    ...context.repo, workflow_id: 'publish-alloy.yml', branch: 'main',
    status: 'success', per_page: 1,
  });
  const run = data.workflow_runs[0];
  if (!run) throw new Error('No successful Alloy publication on main. Publish Alloy or supply an explicit digest.');
  return { ...run, artifact: `alloy-image-manifest-${run.id}-${run.run_attempt}` };
}

function resolveImage(override, repository, manifest, run, sourceRepository) {
  let image = override;
  if (!image) {
    if (!manifest || !run || manifest.schema_version !== 1 ||
        manifest.repository !== sourceRepository || manifest.run_id !== run.id ||
        manifest.run_attempt !== run.run_attempt || manifest.alloy_source_sha !== run.head_sha) {
      throw new Error('Alloy manifest is missing or does not match the selected publish run.');
    }
    image = manifest.alloy_image;
  }
  const prefix = `${repository}@sha256:`;
  if (!repository || typeof image !== 'string' || !image.startsWith(prefix) || image.slice(prefix.length).length !== 64 ||
      !/^[0-9a-f]{64}$/.test(image.slice(prefix.length))) {
    throw new Error('Expected a sha256 digest in the configured ALLOY_REPOSITORY.');
  }
  return image;
}

module.exports = { selectRun, resolveImage };
