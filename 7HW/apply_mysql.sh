export KUBE_NS=st-ab1-kim

kubectl apply -f manifests/mysql/secret.yaml -n $KUBE_NS
kubectl apply -f manifests/mysql/statefulset.yaml -n $KUBE_NS
kubectl apply -f manifests/mysql/service.yaml -n $KUBE_NS
