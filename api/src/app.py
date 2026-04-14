"""
FastAPI application for the Forging Line Delay Diagnostics API.

Exposes:
  POST /diagnose    - receives a piece's cumulative timings, returns diagnosis
  GET  /openapi.json - OpenAPI 3.x spec (auto-served by FastAPI)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .diagnose import diagnose

# Load reference_times.json ONCE at startup
REF_PATH = Path(__file__).resolve().parent.parent / "reference_times.json"
with open(REF_PATH) as f:
    REFERENCE_TIMES: dict[str, dict[str, float]] = json.load(f)


class PieceRequest(BaseModel):
    piece_id: str = Field(..., description="Unique identifier for the piece")
    die_matrix: int = Field(..., description="Die matrix identifier")
    lifetime_2nd_strike_s: Optional[float] = None
    lifetime_3rd_strike_s: Optional[float] = None
    lifetime_4th_strike_s: Optional[float] = None
    lifetime_auxiliary_press_s: Optional[float] = None
    lifetime_bath_s: Optional[float] = None


app = FastAPI(
    title="Forging Line Delay Diagnostics API",
    description=(
        "Receives cumulative timing data for a single forged piece, compares each "
        "segment against reference values, and returns a structured diagnosis."
    ),
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return HTTP 400 with a short error message for invalid bodies (§2.1)."""
    return JSONResponse(
        status_code=400,
        content={"error": "invalid request body"},
    )


@app.post("/diagnose")
def diagnose_endpoint(piece: PieceRequest) -> dict:
    """Diagnose a single piece's delays. See §1.4 for the response schema."""
    piece_dict = piece.model_dump()
    try:
        return diagnose(piece_dict, REFERENCE_TIMES)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Flatten nested detail dicts into the top-level error response shape."""
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})
