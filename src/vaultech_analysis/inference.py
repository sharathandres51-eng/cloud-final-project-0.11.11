"""
Inference service for predicting total piece travel time.

Calls the SageMaker endpoint for predictions instead of loading
the model locally.

Usage as CLI:
    uv run python -m vaultech_analysis.inference --die-matrix 5052 --strike2 18.3 --oee 13.5

Usage as module (for Streamlit):
    from vaultech_analysis.inference import Predictor
    predictor = Predictor()
    result = predictor.predict(die_matrix=5052, lifetime_2nd_strike_s=18.3, oee_cycle_time_s=13.5)
"""

import argparse
import json
import os
import time
from pathlib import Path

import boto3
import pandas as pd


GOLD_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "gold" / "pieces.parquet"
MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models"

# SageMaker endpoint config — can be overridden via environment variables
ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "vaultech-bath-endpoint")
REGION = os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")


class Predictor:
    """Calls the SageMaker endpoint for predictions."""

    def __init__(self, gold_file: Path = GOLD_FILE, model_dir: Path = MODEL_DIR):
        self.runtime = boto3.client("sagemaker-runtime", region_name=REGION)
        self.endpoint_name = ENDPOINT_NAME

        # Load model metadata for validation and defaults
        with open(model_dir / "model_metadata.json") as f:
            self.metadata = json.load(f)

        self.features = self.metadata["features"]
        self.metrics = self.metadata["metrics"]
        self.die_matrices = self.metadata["die_matrices"]
        self.oee_median = self.metadata["oee_median"]

        # Load reference medians per die matrix from gold parquet
        df = pd.read_parquet(gold_file)
        self.reference_medians = (
            df.groupby("die_matrix")[self.features + ["lifetime_bath_s"]]
            .median()
            .to_dict("index")
        )

    def predict(
        self,
        die_matrix: int,
        lifetime_2nd_strike_s: float,
        oee_cycle_time_s: float | None = None,
    ) -> dict:
        """Predict total bath time via SageMaker endpoint."""

        # Validate die_matrix
        if die_matrix not in self.die_matrices:
            return {"error": f"Unknown die_matrix: {die_matrix}. Valid values: {self.die_matrices}"}

        # Use median internally for prediction, but keep original value in response
        oee_for_prediction = oee_cycle_time_s if oee_cycle_time_s is not None else self.oee_median

        # Build CSV payload
        payload = f"{die_matrix},{lifetime_2nd_strike_s},{oee_for_prediction}"

        # Call SageMaker endpoint and measure latency
        start = time.time()
        response = self.runtime.invoke_endpoint(
            EndpointName=self.endpoint_name,
            ContentType="text/csv",
            Body=payload,
        )
        latency_ms = round((time.time() - start) * 1000, 1)

        raw_response = response["Body"].read().decode("utf-8").strip()
        predicted = float(raw_response)

        return {
            "predicted_bath_time_s": round(predicted, 3),
            "die_matrix": die_matrix,
            "lifetime_2nd_strike_s": lifetime_2nd_strike_s,
            "oee_cycle_time_s": oee_cycle_time_s,
            "model_metrics": self.metrics,
            # Debug info for inference panel
            "debug": {
                "endpoint_name": self.endpoint_name,
                "payload": payload,
                "raw_response": raw_response,
                "latency_ms": latency_ms,
            },
        }

    def predict_batch(self, df: pd.DataFrame) -> pd.Series:
        """Predict bath time for a DataFrame of pieces via SageMaker endpoint."""

        df = df.copy()
        df["oee_cycle_time_s"] = df["oee_cycle_time_s"].fillna(self.oee_median)

        predictions = []
        for _, row in df.iterrows():
            payload = f"{int(row['die_matrix'])},{row['lifetime_2nd_strike_s']},{row['oee_cycle_time_s']}"
            response = self.runtime.invoke_endpoint(
                EndpointName=self.endpoint_name,
                ContentType="text/csv",
                Body=payload,
            )
            pred = float(response["Body"].read().decode("utf-8").strip())
            predictions.append(pred)

        return pd.Series(predictions, index=df.index)


def main():
    parser = argparse.ArgumentParser(description="Predict bath time from early-stage features")
    parser.add_argument("--die-matrix", type=int, required=True, help="Die matrix ID")
    parser.add_argument("--strike2", type=float, required=True, help="Lifetime at 2nd strike (seconds)")
    parser.add_argument("--oee", type=float, default=None, help="OEE cycle time (seconds, optional)")
    args = parser.parse_args()

    predictor = Predictor()
    result = predictor.predict(
        die_matrix=args.die_matrix,
        lifetime_2nd_strike_s=args.strike2,
        oee_cycle_time_s=args.oee,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
