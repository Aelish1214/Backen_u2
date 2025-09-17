#!/usr/bin/env bash
set -euo pipefail
NAMESPACE=${1:-monitoring}


kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -


helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update


helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
--namespace "$NAMESPACE" \
-f monitoring/prometheus-grafana-values.yaml


# Metrics Server (for HPA) if not present
kubectl get deployment metrics-server -n kube-system >/dev/null 2>&1 || \
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml