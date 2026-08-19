#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "${script_dir}/.." && pwd)
credentials_file="${project_dir}/.deployment.env"
application_env="${project_dir}/ashare_agent/config/.env"
manifests_dir="${project_dir}/deploy/kubernetes"
namespace=ashare-agent

if [[ ! -f "${credentials_file}" ]]; then
  echo "Missing ${credentials_file}; copy .deployment.env.example first." >&2
  exit 1
fi
if [[ ! -f "${application_env}" ]]; then
  echo "Missing ${application_env}; configure the application first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${credentials_file}"
# shellcheck disable=SC1090
source "${application_env}"
set +a

required_variables=(
  GHCR_USERNAME
  GHCR_TOKEN
  DEEPSEEK_API_KEY
  DEEPSEEK_API_BASE
  DEEPSEEK_MODEL
)
for variable_name in "${required_variables[@]}"; do
  if [[ -z ${!variable_name:-} ]]; then
    echo "${variable_name} must be configured." >&2
    exit 1
  fi
done

kubectl cluster-info >/dev/null
kubectl apply -f "${manifests_dir}/namespace.yaml"

temporary_dir=$(mktemp -d)
trap 'rm -rf -- "${temporary_dir}"' EXIT

if kubectl -n "${namespace}" get secret ashare-agent-secrets >/dev/null 2>&1; then
  postgres_password=$(
    kubectl -n "${namespace}" get secret ashare-agent-secrets \
      -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 --decode
  )
  app_jwt_secret=$(
    kubectl -n "${namespace}" get secret ashare-agent-secrets \
      -o jsonpath='{.data.APP_JWT_SECRET}' | base64 --decode
  )
else
  postgres_password=${POSTGRES_PASSWORD:-$(openssl rand -hex 24)}
  app_jwt_secret=${APP_JWT_SECRET:-$(openssl rand -hex 32)}
fi

if [[ ! ${postgres_password} =~ ^[A-Za-z0-9._~-]+$ ]]; then
  echo "POSTGRES_PASSWORD may only contain URL-safe characters." >&2
  exit 1
fi

database_url="postgresql+asyncpg://ashare_agent:${postgres_password}@postgres:5432/ashare_agent"
app_secret_file="${temporary_dir}/application.env"
{
  printf 'POSTGRES_PASSWORD=%s\n' "${postgres_password}"
  printf 'DATABASE_URL=%s\n' "${database_url}"
  printf 'DEEPSEEK_API_KEY=%s\n' "${DEEPSEEK_API_KEY}"
  printf 'DEEPSEEK_API_BASE=%s\n' "${DEEPSEEK_API_BASE}"
  printf 'DEEPSEEK_MODEL=%s\n' "${DEEPSEEK_MODEL}"
  printf 'APP_JWT_SECRET=%s\n' "${app_jwt_secret}"
  printf 'DEMO_PASSWORD=%s\n' "${DEMO_PASSWORD:-alice123}"
} > "${app_secret_file}"
chmod 0600 "${app_secret_file}"

kubectl -n "${namespace}" create secret generic ashare-agent-secrets \
  --from-env-file="${app_secret_file}" \
  --dry-run=client -o yaml | kubectl apply -f -

docker_config_file="${temporary_dir}/docker-config.json"
if [[ ! ${GHCR_USERNAME} =~ ^[A-Za-z0-9-]+$ ]] \
  || [[ ! ${GHCR_TOKEN} =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "GHCR credentials contain unsupported characters." >&2
  exit 1
fi
docker_auth=$(printf '%s' "${GHCR_USERNAME}:${GHCR_TOKEN}" | base64 --wrap=0)
printf '{"auths":{"ghcr.io":{"username":"%s","password":"%s","auth":"%s"}}}' \
  "${GHCR_USERNAME}" "${GHCR_TOKEN}" "${docker_auth}" > "${docker_config_file}"
chmod 0600 "${docker_config_file}"

kubectl -n "${namespace}" create secret generic ghcr-credentials \
  --type=kubernetes.io/dockerconfigjson \
  --from-file=.dockerconfigjson="${docker_config_file}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "${namespace}" delete job database-migration \
  --ignore-not-found --wait=true
kubectl apply -k "${manifests_dir}"

kubectl -n "${namespace}" rollout status statefulset/postgres --timeout=10m
kubectl -n "${namespace}" rollout status statefulset/redis --timeout=10m
kubectl -n "${namespace}" wait --for=condition=Complete \
  job/database-migration --timeout=10m
kubectl -n "${namespace}" rollout status deployment/api --timeout=10m
kubectl -n "${namespace}" rollout status deployment/worker --timeout=10m
kubectl -n "${namespace}" rollout status deployment/frontend --timeout=10m

kubectl -n "${namespace}" get pods -o wide
echo "Frontend: http://10.192.54.98:30080"
echo "API docs: http://10.192.54.98:30800/docs"
