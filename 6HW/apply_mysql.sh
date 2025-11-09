export KUBE_NS=st-ab1-kim

kubectl apply -f manifests_1/mysql/secret.yaml -n $KUBE_NS
kubectl apply -f manifests_1/mysql/statefulset.yaml -n $KUBE_NS
kubectl apply -f manifests_1/mysql/service.yaml -n $KUBE_NS

export KUBE_NS=st-ab1-kim

kubectl apply -f manifests_2/mysql/secret.yaml -n $KUBE_NS
kubectl apply -f manifests_2/mysql/statefulset.yaml -n $KUBE_NS
kubectl apply -f manifests_2/mysql/service.yaml -n $KUBE_NS
