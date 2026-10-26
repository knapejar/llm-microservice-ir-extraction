#!/bin/sh
# Run the agent once on every system of the benchmark pool, three at a time.
#   CLONE=<dir with the checkouts> LLM_API_KEY=<key> [ONLY=<name regex>] [STEPS=200] \
#     sh run_pool.sh <model> [effort] [base-url]
# Writes out/pool/agent_ir.<unit>.<model>.<effort>.json (+ .log, .messages.json);
# units that already have an output are skipped, so a rerun only does the rest.
# Systems with a few hundred endpoints are split into units (a service, a repo or a
# module): one agent run declares itself done long before it has seen all of them.
MODEL=${1:?model}
export MODEL EFFORT=${2:-none} CLONE=${CLONE:?checkout dir} BASE_URL=${3:-https://pass.wafer.ai/v1} STEPS=${STEPS:-200}
cd "$(dirname "$0")" && mkdir -p out/pool
while read -r name repos; do
  [ -f "out/pool/agent_ir.$name.$MODEL.$EFFORT.json" ] || echo "$name $repos"
done <<'EOF' | grep -E "^(${ONLY:-[^ ]+}) " | xargs -P 3 -L 1 sh -c '
  name=$0; for r; do set -- "$@" "$CLONE/$r"; shift; done
  echo "start $name"
  python agent_extract.py --repo "$@" --system-name "$name" --model "$MODEL" --base-url "$BASE_URL" \
    --native-tools --effort "$EFFORT" --max-tokens 24000 --max-steps "$STEPS" \
    --out "out/pool/agent_ir.$name.$MODEL.$EFFORT.json" >/dev/null 2>"out/pool/$name.$MODEL.$EFFORT.stderr"
  echo "done  $name (exit $?)"'
spring-cloud-movie-recommendation spring-cloud-movie-recommendation
golang-crud-rest-api-gin golang-crud-rest-api-gin
crud-tutorial-csharp crud-tutorial-csharp
node-js-restful-api-example node-js-restful-api-example
E-commerce-Microservice E-commerce-Microservice
rasa-sdk rasa-sdk
microservices-demo microservices-demo
robot-shop robot-shop
sock-shop sock-shop/front-end sock-shop/catalogue sock-shop/carts sock-shop/orders sock-shop/payment sock-shop/user sock-shop/shipping sock-shop/queue-master
pitstop pitstop
eShop eShop
ccpay-payment-app ccpay-payment-app
pravega pravega
geoserver-cloud geoserver-cloud
xs2a xs2a
apollo apollo
train-ticket train-ticket
kapua-rest-api kapua/rest-api kapua/job-engine
openlmis-auth openlmis/openlmis-auth
openlmis-cce openlmis/openlmis-cce
openlmis-diagnostics openlmis/openlmis-diagnostics
openlmis-example-extensions openlmis/openlmis-example-extensions
openlmis-fulfillment openlmis/openlmis-fulfillment
openlmis-hapifhir openlmis/openlmis-hapifhir
openlmis-notification openlmis/openlmis-notification
openlmis-referencedata openlmis/openlmis-referencedata
openlmis-requisition openlmis/openlmis-requisition
openlmis-stockmanagement openlmis/openlmis-stockmanagement
inlong-manager inlong/inlong-manager
inlong-tubemq inlong/inlong-tubemq
camunda-optimize camunda/optimize
camunda-gateway-rest camunda/zeebe/gateway-rest
camunda-other camunda/zeebe/dynamic-config camunda/dist camunda/webapp camunda/authentication camunda/operate
spinnaker-gate-web spinnaker/gate/gate-web
spinnaker-orca spinnaker/orca
spinnaker-clouddriver spinnaker/clouddriver
spinnaker-front50 spinnaker/front50
spinnaker-echo spinnaker/echo
spinnaker-fiat spinnaker/fiat
spinnaker-igor spinnaker/igor
spinnaker-kayenta spinnaker/kayenta
spinnaker-keel spinnaker/keel
spinnaker-rosco spinnaker/rosco
EOF
