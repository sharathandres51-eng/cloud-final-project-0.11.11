"""
SageMaker deployment script — packages, registers, and deploys the XGBoost model.

Usage:
    uv run python deploy/deploy_sagemaker.py \
      --bucket your-bucket-name \
      --region eu-west-1 \
      --endpoint-name your-endpoint-name \
      --model-package-group your-group-name \
      --role-arn arn:aws:iam::123456789012:role/SageMakerExecutionRole
"""

import argparse
import json
import tarfile
import shutil
import time
from pathlib import Path

import boto3

# XGBoost 3.0-5 built-in container image URI per region
XGBOOST_IMAGE_URIS = {
    "eu-west-1": "141502667606.dkr.ecr.eu-west-1.amazonaws.com/sagemaker-xgboost:3.0-5",
    "us-east-1": "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-xgboost:3.0-5",
    "us-west-2": "246618743249.dkr.ecr.us-west-2.amazonaws.com/sagemaker-xgboost:3.0-5",
}

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_FILE = MODEL_DIR / "xgboost_bath_predictor.json"
METADATA_FILE = MODEL_DIR / "model_metadata.json"


def package_model(model_path: Path, output_dir: Path) -> Path:
    """Package the XGBoost model as a .tar.gz archive for SageMaker.

    SageMaker's built-in XGBoost container expects a file named
    'xgboost-model' at the root of the archive.

    Args:
        model_path: Path to the trained model JSON file.
        output_dir: Directory where the .tar.gz will be created.

    Returns:
        Path to the created .tar.gz file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy and rename model file to what SageMaker expects
    renamed = output_dir / "xgboost-model"
    shutil.copy(model_path, renamed)

    tar_path = output_dir / "model.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(renamed, arcname="xgboost-model")

    renamed.unlink()
    return tar_path


def upload_to_s3(local_path: Path, bucket: str, key: str) -> str:
    """Upload a local file to S3. Returns the full S3 URI."""
    s3 = boto3.client("s3")
    s3.upload_file(str(local_path), bucket, key)
    return f"s3://{bucket}/{key}"


def register_model(
    s3_model_uri: str,
    model_package_group_name: str,
    region: str,
    metrics: dict,
) -> str:
    """Register the model in SageMaker Model Registry. Returns the Model Package ARN."""
    sm = boto3.client("sagemaker", region_name=region)

    # Create Model Package Group if it doesn't exist
    try:
        sm.create_model_package_group(
            ModelPackageGroupName=model_package_group_name,
            ModelPackageGroupDescription="VaultTech XGBoost bath time predictor",
        )
        print(f"  Created Model Package Group: {model_package_group_name}")
    except sm.exceptions.ClientError as e:
        if "already exists" in str(e) or "ConflictException" in str(type(e).__name__):
            print(f"  Model Package Group already exists: {model_package_group_name}")
        else:
            raise

    # Get XGBoost container image URI
    image_uri = XGBOOST_IMAGE_URIS[region]

    # Register model package
    response = sm.create_model_package(
        ModelPackageGroupName=model_package_group_name,
        ModelPackageDescription="XGBoost bath time predictor — trained on forging line data",
        InferenceSpecification={
            "Containers": [
                {
                    "Image": image_uri,
                    "ModelDataUrl": s3_model_uri,
                }
            ],
            "SupportedContentTypes": ["text/csv"],
            "SupportedResponseMIMETypes": ["text/csv"],
        },
        ModelApprovalStatus="Approved",
        ModelMetrics={
            "ModelQuality": {
                "Statistics": {
                    "ContentType": "application/json",
                    "S3Uri": s3_model_uri,  # placeholder — metrics stored in metadata
                }
            }
        },
        CustomerMetadataProperties={
            "rmse": str(metrics["rmse"]),
            "mae": str(metrics["mae"]),
            "r2": str(metrics["r2"]),
        },
    )

    return response["ModelPackageArn"]


def deploy_endpoint(
    model_package_arn: str,
    endpoint_name: str,
    region: str,
    role_arn: str,
    instance_type: str = "ml.t2.medium",
) -> str:
    """Deploy a real-time SageMaker endpoint. Returns the endpoint name."""
    sm = boto3.client("sagemaker", region_name=region)
    model_name = endpoint_name + "-model"
    config_name = endpoint_name + "-config"

    # Create SageMaker Model from registered package
    sm.create_model(
        ModelName=model_name,
        ExecutionRoleArn=role_arn,
        Containers=[{"ModelPackageName": model_package_arn}],
    )
    print(f"  Created model: {model_name}")

    # Create Endpoint Configuration
    sm.create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[
            {
                "VariantName": "primary",
                "ModelName": model_name,
                "InstanceType": instance_type,
                "InitialInstanceCount": 1,
            }
        ],
    )
    print(f"  Created endpoint config: {config_name}")

    # Create Endpoint
    sm.create_endpoint(
        EndpointName=endpoint_name,
        EndpointConfigName=config_name,
    )
    print(f"  Waiting for endpoint '{endpoint_name}' to be InService...")

    # Wait for InService
    waiter = sm.get_waiter("endpoint_in_service")
    waiter.wait(EndpointName=endpoint_name, WaiterConfig={"Delay": 30, "MaxAttempts": 40})

    return endpoint_name


def test_endpoint(endpoint_name: str, region: str) -> dict:
    """Test the deployed endpoint with sample pieces."""
    runtime = boto3.client("sagemaker-runtime", region_name=region)

    samples = [
        {"die_matrix": 5052, "lifetime_2nd_strike_s": 18.3, "oee_cycle_time_s": 13.5},
        {"die_matrix": 5090, "lifetime_2nd_strike_s": 17.8, "oee_cycle_time_s": 14.0},
        {"die_matrix": 5091, "lifetime_2nd_strike_s": 25.0, "oee_cycle_time_s": 13.0},
    ]

    results = []
    for sample in samples:
        payload = f"{sample['die_matrix']},{sample['lifetime_2nd_strike_s']},{sample['oee_cycle_time_s']}"
        response = runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="text/csv",
            Body=payload,
        )
        prediction = float(response["Body"].read().decode().strip())
        results.append({
            "input": sample,
            "predicted_bath_time_s": round(prediction, 3),
            "in_range": 40 <= prediction <= 80,
        })

    return {"predictions": results, "all_in_range": all(r["in_range"] for r in results)}


def main():
    parser = argparse.ArgumentParser(description="Deploy XGBoost model to SageMaker")
    parser.add_argument("--bucket", required=True, help="S3 bucket for model artifact")
    parser.add_argument("--region", default="eu-west-1", help="AWS region")
    parser.add_argument("--endpoint-name", required=True, help="SageMaker endpoint name")
    parser.add_argument("--model-package-group", required=True, help="Model Package Group name")
    parser.add_argument("--role-arn", required=True, help="SageMaker execution role ARN")
    args = parser.parse_args()

    with open(METADATA_FILE) as f:
        metadata = json.load(f)

    print("=" * 60)
    print("SageMaker Deployment Pipeline")
    print("=" * 60)

    print("\n[1/5] Packaging model artifact...")
    tar_path = package_model(MODEL_FILE, MODEL_DIR)
    print(f"  Created: {tar_path}")

    print("\n[2/5] Uploading to S3...")
    s3_key = "models/xgboost-bath-predictor/model.tar.gz"
    s3_uri = upload_to_s3(tar_path, args.bucket, s3_key)
    print(f"  Uploaded: {s3_uri}")

    print("\n[3/5] Registering in Model Registry...")
    model_package_arn = register_model(
        s3_uri, args.model_package_group, args.region, metadata["metrics"]
    )
    print(f"  Registered: {model_package_arn}")

    print("\n[4/5] Deploying endpoint...")
    endpoint = deploy_endpoint(
        model_package_arn, args.endpoint_name, args.region, args.role_arn
    )
    print(f"  Endpoint live: {endpoint}")

    print("\n[5/5] Testing endpoint...")
    results = test_endpoint(args.endpoint_name, args.region)
    print(f"  Results: {json.dumps(results, indent=2)}")

    print("\n" + "=" * 60)
    print("Deployment complete!")
    print(f"  Endpoint:       {args.endpoint_name}")
    print(f"  Model Package:  {model_package_arn}")
    print(f"  S3 artifact:    {s3_uri}")
    print("=" * 60)


if __name__ == "__main__":
    main()
