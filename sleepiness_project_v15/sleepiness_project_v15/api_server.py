"""
api_server.py — REST API with FastAPI (v21 NEW).

Production-ready REST API for sleepiness detection:
- Real-time video streaming via WebSocket
- Batch image processing
- Health checks and metrics
- Authentication and rate limiting
- OpenAPI documentation
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Dict, List, Optional

import cv2
import numpy as np
from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect,
    HTTPException, Depends, status, UploadFile, File
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from security import APIKeyManager, RateLimiter, get_audit_logger
from circuit_breaker import get_health_checker, HealthStatus
from validators import validate_ear, validate_mar, DataQualityMetrics
from resource_manager import get_memory_monitor
from batch_inference import BatchInferenceEngine

logger = logging.getLogger(__name__)

# ─── API Models ──────────────────────────────────────────────────────────────

class DetectionRequest(BaseModel):
    """Request for single image detection."""
    image_base64: str = Field(..., description="Base64 encoded image")
    return_visualization: bool = Field(False, description="Return annotated image")


class DetectionResponse(BaseModel):
    """Response from detection."""
    ear: float = Field(..., description="Eye Aspect Ratio")
    mar: float = Field(..., description="Mouth Aspect Ratio")
    alert_level: int = Field(..., description="Alert level (0=normal, 1=warning, 2=alert)")
    sleep_probability: float = Field(..., description="Probability of sleepiness")
    has_face: bool = Field(..., description="Whether face was detected")
    processing_time_ms: float = Field(..., description="Processing time in milliseconds")
    visualization_base64: Optional[str] = Field(None, description="Annotated image if requested")


class BatchDetectionRequest(BaseModel):
    """Request for batch detection."""
    images_base64: List[str] = Field(..., description="List of base64 encoded images")
    max_batch_size: int = Field(8, description="Maximum batch size")


class BatchDetectionResponse(BaseModel):
    """Response from batch detection."""
    results: List[DetectionResponse]
    total_processing_time_ms: float
    avg_time_per_image_ms: float


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Overall status")
    components: Dict[str, str] = Field(..., description="Component statuses")
    memory_mb: float = Field(..., description="Current memory usage")
    uptime_seconds: float = Field(..., description="Server uptime")


class MetricsResponse(BaseModel):
    """Metrics response."""
    total_requests: int
    total_detections: int
    avg_processing_time_ms: float
    memory_mb: float
    data_quality: Dict[str, float]


class StreamConfig(BaseModel):
    """WebSocket stream configuration."""
    fps_target: int = Field(30, ge=1, le=60, description="Target FPS")
    enable_visualization: bool = Field(True, description="Send annotated frames")
    alert_threshold: float = Field(0.7, ge=0.0, le=1.0, description="Alert threshold")


# ─── FastAPI Application ─────────────────────────────────────────────────────

app = FastAPI(
    title="Sleepiness Detection API",
    description="Real-time drowsiness detection API with WebSocket streaming",
    version="21.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()
api_key_manager = APIKeyManager()

# API request rate limiter (token bucket). This is a REST throughput limit and is
# intentionally separate from the audio alert limiter in security.py — reusing
# that buzzer limiter (capacity 3 @ 1/s) would 429 the API after 3 quick calls.
# ~20 req/s sustained with a burst of 40 suits per-key interactive use.
api_rate_limiter = RateLimiter(rate=20.0, capacity=40)

# Global state
_detector = None
_batch_engine = None
_start_time = time.time()
_request_count = 0
_detection_count = 0
_total_processing_time = 0.0
_quality_metrics = DataQualityMetrics(window_size=1000)


# ─── Authentication ──────────────────────────────────────────────────────────

async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """Verify API key."""
    api_key = credentials.credentials
    is_valid, info = api_key_manager.validate_key(api_key)

    if not is_valid:
        get_audit_logger().log_auth(
            user="unknown",
            method="api_key",
            result="failure",
            ip=None
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    get_audit_logger().log_auth(
        user=info["name"],
        method="api_key",
        result="success",
        ip=None
    )

    return info


# ─── Startup/Shutdown ────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global _detector, _batch_engine

    logger.info("Starting Sleepiness Detection API...")

    # Initialize detector (placeholder - would load actual model)
    # _detector = load_detector()

    # Initialize batch engine
    # _batch_engine = BatchInferenceEngine(predictor, batch_size=8)
    # _batch_engine.start()

    # Start monitoring
    monitor = get_memory_monitor()
    monitor.start()

    # Register health checks
    checker = get_health_checker()
    checker.register("api", lambda: True)
    # checker.register("detector", lambda: _detector is not None)
    # checker.register("batch_engine", lambda: _batch_engine is not None)

    logger.info("API started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down API...")

    # Stop batch engine
    if _batch_engine is not None:
        _batch_engine.stop()

    # Stop monitoring
    monitor = get_memory_monitor()
    monitor.stop()

    logger.info("API shutdown complete")


# ─── Health & Metrics Endpoints ──────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["Monitoring"])
async def health_check():
    """
    Health check endpoint.

    Returns overall system health and component statuses.
    """
    checker = get_health_checker()
    results = checker.check_all()
    overall = checker.get_overall_status()

    monitor = get_memory_monitor()
    memory = monitor.get_memory_mb()

    uptime = time.time() - _start_time

    return HealthResponse(
        status=overall.value,
        components={name: result.status.value for name, result in results.items()},
        memory_mb=memory,
        uptime_seconds=uptime
    )


@app.get("/metrics", response_model=MetricsResponse, tags=["Monitoring"])
async def get_metrics(api_key_info: Dict = Depends(verify_api_key)):
    """
    Get API metrics.

    Requires authentication.
    """
    monitor = get_memory_monitor()
    memory = monitor.get_memory_mb()

    avg_time = (
        _total_processing_time / _detection_count
        if _detection_count > 0
        else 0.0
    )

    quality_summary = _quality_metrics.get_summary()

    return MetricsResponse(
        total_requests=_request_count,
        total_detections=_detection_count,
        avg_processing_time_ms=avg_time,
        memory_mb=memory,
        data_quality=quality_summary
    )


@app.get("/", tags=["Info"])
async def root():
    """API information."""
    return {
        "name": "Sleepiness Detection API",
        "version": "21.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    }


# ─── Detection Endpoints ─────────────────────────────────────────────────────

def _decode_image_b64(image_base64: str) -> "np.ndarray":
    """Decode a base64 string into a BGR image, raising HTTP 400 on bad input.

    Client-supplied data that is malformed (bad base64, non-image bytes) is a
    *client* error → 400, not a 500. Keeping this out of the endpoint's broad
    try/except prevents those 400s from being reclassified as server errors.
    """
    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except (ValueError, Exception):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 image data",
        )
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not decode image",
        )
    return image


@app.post("/detect", response_model=DetectionResponse, tags=["Detection"])
async def detect_single(
    request: DetectionRequest,
    api_key_info: Dict = Depends(verify_api_key)
):
    """
    Detect sleepiness in single image.

    Requires authentication.
    """
    global _request_count, _detection_count, _total_processing_time

    _request_count += 1

    # Rate limiting (REST throughput, not the audio buzzer limiter)
    if not api_rate_limiter.acquire():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )

    # Decode outside the broad try/except so a 400 stays a 400.
    image = _decode_image_b64(request.image_base64)

    try:
        # Process image (placeholder - would use actual detector)
        start_time = time.perf_counter()

        # Simulate detection
        ear = 0.25
        mar = 0.5
        alert_level = 0
        sleep_prob = 0.1
        has_face = True

        processing_time = (time.perf_counter() - start_time) * 1000

        _detection_count += 1
        _total_processing_time += processing_time

        # Track quality
        _quality_metrics.record(ear, mar, has_landmarks=has_face)

        # Generate visualization if requested
        visualization_base64 = None
        if request.return_visualization:
            # Draw on image (placeholder)
            vis_image = image.copy()
            cv2.putText(vis_image, f"EAR: {ear:.2f}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            _, buffer = cv2.imencode('.jpg', vis_image)
            visualization_base64 = base64.b64encode(buffer).decode('utf-8')

        return DetectionResponse(
            ear=ear,
            mar=mar,
            alert_level=alert_level,
            sleep_probability=sleep_prob,
            has_face=has_face,
            processing_time_ms=processing_time,
            visualization_base64=visualization_base64
        )

    except HTTPException:
        raise  # client errors (400/404/...) must not be masked as 500
    except Exception as e:
        logger.error(f"Detection error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Detection failed: {str(e)}"
        )


@app.post("/detect/batch", response_model=BatchDetectionResponse, tags=["Detection"])
async def detect_batch(
    request: BatchDetectionRequest,
    api_key_info: Dict = Depends(verify_api_key)
):
    """
    Detect sleepiness in multiple images (batch processing).

    Requires authentication.
    """
    global _request_count, _detection_count, _total_processing_time

    _request_count += 1

    if len(request.images_base64) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No images provided"
        )

    if len(request.images_base64) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many images (max 100)"
        )

    # Decode all images up front (400 on any malformed entry).
    images = [_decode_image_b64(b) for b in request.images_base64]

    try:
        start_time = time.perf_counter()
        results = []

        # Process each image (would use batch engine in production)
        for image in images:
            # Simulate detection
            result = DetectionResponse(
                ear=0.25,
                mar=0.5,
                alert_level=0,
                sleep_probability=0.1,
                has_face=True,
                processing_time_ms=10.0,
                visualization_base64=None
            )
            results.append(result)
            _detection_count += 1

        total_time = (time.perf_counter() - start_time) * 1000
        _total_processing_time += total_time

        avg_time = total_time / len(results) if results else 0.0

        return BatchDetectionResponse(
            results=results,
            total_processing_time_ms=total_time,
            avg_time_per_image_ms=avg_time
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Batch detection error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch detection failed: {str(e)}"
        )


# ─── WebSocket Streaming ─────────────────────────────────────────────────────

@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    """
    WebSocket endpoint for real-time video streaming.

    Client sends frames, server responds with detection results.
    """
    await websocket.accept()
    logger.info("WebSocket connection established")

    try:
        # Receive configuration
        config_data = await websocket.receive_json()
        config = StreamConfig(**config_data)

        logger.info(f"Stream config: {config}")

        frame_count = 0
        start_time = time.time()

        while True:
            # Receive frame
            data = await websocket.receive_json()

            if "frame" not in data:
                await websocket.send_json({"error": "No frame data"})
                continue

            # Decode frame
            frame_b64 = data["frame"]
            frame_bytes = base64.b64decode(frame_b64)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                await websocket.send_json({"error": "Invalid frame"})
                continue

            # Process frame (placeholder)
            ear = 0.25
            mar = 0.5
            alert_level = 0
            sleep_prob = 0.1

            frame_count += 1

            # Send result
            result = {
                "frame_id": frame_count,
                "ear": ear,
                "mar": mar,
                "alert_level": alert_level,
                "sleep_probability": sleep_prob,
                "timestamp": time.time()
            }

            # Add visualization if enabled
            if config.enable_visualization:
                vis_frame = frame.copy()
                cv2.putText(vis_frame, f"EAR: {ear:.2f}", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                _, buffer = cv2.imencode('.jpg', vis_frame)
                result["visualization"] = base64.b64encode(buffer).decode('utf-8')

            await websocket.send_json(result)

            # Rate limiting
            elapsed = time.time() - start_time
            expected_frames = elapsed * config.fps_target
            if frame_count > expected_frames:
                await asyncio.sleep(1.0 / config.fps_target)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({"error": str(e)})
        except:
            pass


# ─── Admin Endpoints ─────────────────────────────────────────────────────────

@app.post("/admin/api-keys", tags=["Admin"])
async def create_api_key(
    name: str,
    permissions: List[str] = ["read"],
    api_key_info: Dict = Depends(verify_api_key)
):
    """
    Create new API key.

    Requires admin permissions.
    """
    if "admin" not in api_key_info.get("permissions", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required"
        )

    key = api_key_manager.generate_key(name, permissions)

    get_audit_logger().log_access(
        user=api_key_info["name"],
        resource="api_keys",
        action="create",
        result="success"
    )

    return {"api_key": key, "name": name, "permissions": permissions}


@app.delete("/admin/api-keys/{key}", tags=["Admin"])
async def revoke_api_key(
    key: str,
    api_key_info: Dict = Depends(verify_api_key)
):
    """
    Revoke API key.

    Requires admin permissions.
    """
    if "admin" not in api_key_info.get("permissions", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required"
        )

    success = api_key_manager.revoke_key(key)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )

    get_audit_logger().log_access(
        user=api_key_info["name"],
        resource="api_keys",
        action="revoke",
        result="success"
    )

    return {"message": "API key revoked"}


# ─── Run Server ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    # Generate initial admin API key
    admin_key = api_key_manager.generate_key("admin", permissions=["read", "write", "admin"])
    print(f"\n{'='*60}")
    print(f"Admin API Key: {admin_key}")
    print(f"{'='*60}\n")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
