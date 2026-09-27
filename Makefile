.PHONY: verify fmt plan
verify:
	deploy/scripts/validate.sh
fmt:
	terraform fmt -recursive infra
plan:
	@test -n "$(DEV_VARS)" && test -n "$(DEV_BACKEND)" || { echo 'Set DEV_VARS and DEV_BACKEND to absolute profile paths'; exit 2; }
	terraform -chdir=infra/environments/dev init -backend-config="$(DEV_BACKEND)"
	terraform -chdir=infra/environments/dev plan -var-file="$(DEV_VARS)"
