export KUBE_NS=st-ab1-kim

kubectl apply -f manifests/sla_calculator/sla-calculator-configmap.yaml -n $KUBE_NS
kubectl apply -f manifests/sla_calculator/sla-calculator-secrets.yaml -n $KUBE_NS
kubectl apply -f manifests/sla_calculator/sla-calculator-deployment.yaml -n $KUBE_NS