export KUBE_NS=st-ab1-kim

kubectl apply -f manifests/prober/oncall-prober-configmap.yaml -n $KUBE_NS

kubectl apply -f manifests/prober/oncall-prober-deployment.yaml -n $KUBE_NS

kubectl apply -f manifests/prober/oncall-prober-service.yaml -n $KUBE_NS
