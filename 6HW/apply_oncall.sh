export KUBE_NS=st-ab1-kim


KUBE_NS=$KUBE_NS envsubst < manifests_1/oncall/config.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests_1/oncall/vector-config.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests_1/oncall/deployment.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests_1/oncall/service.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests_1/oncall/ingress.yaml | kubectl apply -f - -n $KUBE_NS




export KUBE_NS=st-ab1-kim


KUBE_NS=$KUBE_NS envsubst < manifests_2/oncall/config.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests_2/oncall/vector-config.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests_2/oncall/deployment.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests_2/oncall/service.yaml | kubectl apply -f - -n $KUBE_NS
KUBE_NS=$KUBE_NS envsubst < manifests_2/oncall/ingress.yaml | kubectl apply -f - -n $KUBE_NS