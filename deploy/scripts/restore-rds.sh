#!/usr/bin/env bash
set -euo pipefail
export AWS_REGION="${AWS_REGION:-ap-southeast-1}"
source_db=${1:?Usage: restore-rds.sh SOURCE_DB SNAPSHOT_ID NEW_DB_ID}
snapshot=${2:?}; restored=${3:?}
[[ $restored != "$source_db" ]] || { echo 'Restore must use a new instance identifier' >&2; exit 1; }
source_json=$(aws rds describe-db-instances --db-instance-identifier "$source_db" --output json)
subnet=$(jq -er '.DBInstances[0].DBSubnetGroup.DBSubnetGroupName' <<<"$source_json")
sg=$(jq -er '.DBInstances[0].VpcSecurityGroups[0].VpcSecurityGroupId' <<<"$source_json")
parameter=$(jq -er '.DBInstances[0].DBParameterGroups[0].DBParameterGroupName' <<<"$source_json")
aws rds restore-db-instance-from-db-snapshot --db-instance-identifier "$restored" --db-snapshot-identifier "$snapshot" --db-instance-class db.t4g.micro --db-subnet-group-name "$subnet" --vpc-security-group-ids "$sg" --db-parameter-group-name "$parameter" --no-publicly-accessible --no-multi-az --deletion-protection --output json >/dev/null
aws rds wait db-instance-available --db-instance-identifier "$restored"
aws rds describe-db-instances --db-instance-identifier "$restored" --query 'DBInstances[0].{Identifier:DBInstanceIdentifier,Endpoint:Endpoint.Address,Encrypted:StorageEncrypted,Public:PubliclyAccessible}' --output json
printf '%s\n' 'Restore created separately. Verify schema and expected synthetic balances through an isolated ECS task before considering any cutover. This script never changes the application endpoint.'
