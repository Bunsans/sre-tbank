# DaemonSet

1) Создаем демонсет

```bash
kubectl apply -f daemonset.yml
```

В ответ должны увидеть

```bash
daemonset.apps/node-exporter created
```

2) Смотрим на поды

```bash
kubectl get pod -o wide
```

Видим
```bash
NAME                             READY   STATUS    RESTARTS   AGE   IP          NODE
node-exporter-2ch5q              1/1     Running   0          18s   10.128.0.6  node-1
node-exporter-r984x              1/1     Running   0          18s   10.128.0.38 node-2
node-exporter-t4x4s              1/1     Running   0          18s   10.128.0.9  node-3
```

3) Удаляем daemonset
```bash
kubectl delete -f daemonset.yml
```
