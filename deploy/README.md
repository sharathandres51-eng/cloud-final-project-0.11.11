# SageMaker Deployment — Task 10

## Prerequisites

1. AWS CLI configured with credentials that have SageMaker, S3, and IAM permissions
2. An S3 bucket in `eu-west-1` (create once: `aws s3 mb s3://your-bucket-name --region eu-west-1`)
3. A SageMaker execution role with `AmazonSageMakerFullAccess` and `AmazonS3FullAccess`

## Resource Names

| Resource              | Name                          |
|-----------------------|-------------------------------|
| S3 bucket             | `vaultech-model-artifacts`    |
| Model Package Group   | `vaultech-bath-predictor`     |
| Endpoint name         | `vaultech-bath-endpoint`      |
| AWS region            | `eu-west-1`                   |

## How to deploy

```bash
uv run python deploy/deploy_sagemaker.py \
  --bucket vaultech-model-artifacts \
  --region eu-west-1 \
  --endpoint-name vaultech-bath-endpoint \
  --model-package-group vaultech-bath-predictor \
  --role-arn arn:aws:iam::<YOUR_ACCOUNT_ID>:role/SageMakerExecutionRole
```

The script will:
1. Package `models/xgboost_bath_predictor.json` → `model.tar.gz` (renamed to `xgboost-model` inside)
2. Upload to `s3://vaultech-model-artifacts/models/xgboost-bath-predictor/model.tar.gz`
3. Register in Model Registry under `vaultech-bath-predictor` with RMSE/MAE/R² metrics
4. Deploy a real-time endpoint on `ml.t2.medium` in `eu-west-1` (~5–10 minutes)
5. Run test invocations and compare against local model predictions

## How to run the validation tests

```bash
export SAGEMAKER_MODEL_PACKAGE_GROUP="vaultech-bath-predictor"
export SAGEMAKER_ENDPOINT_NAME="vaultech-bath-endpoint"
export AWS_DEFAULT_REGION="eu-west-1"
uv run pytest tests/test_sagemaker.py -v
```

## How to delete the endpoint (to avoid charges)

```bash
aws sagemaker delete-endpoint --endpoint-name vaultech-bath-endpoint --region eu-west-1
aws sagemaker delete-endpoint-config --endpoint-config-name vaultech-bath-endpoint-config --region eu-west-1
```
