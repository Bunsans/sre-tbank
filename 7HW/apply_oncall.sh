export KUBE_NS=st-ab1-kim


KUBE_NS=$KUBE_NS envsubst < manifests/oncall/config.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests/oncall/vector-config.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests/oncall/deployment.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests/oncall/service.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests/oncall/ingress.yaml | kubectl apply -f - -n $KUBE_NS