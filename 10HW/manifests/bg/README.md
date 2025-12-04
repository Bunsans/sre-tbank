kubectl apply -f 03-bg-blue.yaml
kubectl apply -f 03-bg-service-v1.yaml



kubectl apply -f 03-bg-green.yaml
# wait until ok

kubectl apply -f 03-bg-service-v2.yaml

