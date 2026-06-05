"""
Document Analysis Endpoints
POST /api/v1/analyze/document - Analyze document asynchronously
GET /api/v1/analyze/{job_id} - Check analysis job status
"""
import uuid
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status, Depends
from fastapi import Request
from fastapi.responses import JSONResponse
from api.models import DocumentAnalysisRequest, DocumentAnalysisSummary, AnalysisJobResponse
from api.auth import get_current_user, CurrentUser
from celery_app import analyze_document_task, TaskStatus
import structlog

router = APIRouter(prefix="/api/v1/analyze", tags=["document-analysis"])
logger = structlog.get_logger(__name__)


@router.post(
    "/document",
    response_model=AnalysisJobResponse,
    summary="Analyze document asynchronously",
    description="Upload or provide document text for analysis. Returns immediately with job ID."
)
async def analyze_document(
    request: DocumentAnalysisRequest,
    http_request: Request,
    current_user: CurrentUser = Depends(get_current_user)
) -> AnalysisJobResponse:
    """
    Analyze a legal document asynchronously
    
    - **file_url**: URL to document (if not uploading)
    - **file_path**: Local file path (if not uploading)
    - **text**: Document text directly (if not uploading)
    - **document_type**: Type of document (contract, lawsuit, etc.)
    - **extract_remedies**: Extract remedy clauses
    - **extract_deadlines**: Extract important deadlines
    - **extract_obligations**: Extract obligations
    
    Returns job ID to track progress
    """
    if not any([request.file_url, request.file_path, request.text]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide file_url, file_path, or text"
        )
    
    # Generate document ID and job ID
    document_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    
    logger.info(
        "Starting document analysis",
        user_id=current_user.user_id,
        document_id=document_id,
        job_id=job_id
    )
    
    # Queue async task
    text = request.text or f"Content from {request.file_url or request.file_path}"
    task = analyze_document_task.delay(
        user_id=current_user.user_id,
        document_id=document_id,
        text=text,
        document_type=request.document_type,
        request_id=getattr(http_request.state, "request_id", None),
    )
    
    return AnalysisJobResponse(
        job_id=task.id,
        status="pending",
        created_at=__import__('datetime').datetime.utcnow()
    )


@router.get(
    "/{job_id}",
    response_model=AnalysisJobResponse,
    summary="Get analysis job status"
)
async def get_analysis_status(
    job_id: str,
    current_user: CurrentUser = Depends(get_current_user)
) -> AnalysisJobResponse:
    """Get status and result of analysis job"""
    
    status_info = TaskStatus.get_task_status(job_id)
    
    return AnalysisJobResponse(
        job_id=job_id,
        status=status_info["status"],
        created_at=__import__('datetime').datetime.utcnow(),
        result_url=f"/api/v1/analyze/{job_id}/result" if status_info["status"] == "completed" else None
    )


@router.get(
    "/{job_id}/result",
    response_model=DocumentAnalysisSummary,
    summary="Get analysis result"
)
async def get_analysis_result(
    job_id: str,
    current_user: CurrentUser = Depends(get_current_user)
) -> DocumentAnalysisSummary:
    """Get the complete analysis result"""
    
    status_info = TaskStatus.get_task_status(job_id)
    
    if status_info["status"] != "completed":
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "job_id": job_id,
                "status": status_info["status"],
                "detail": f"Job is still {status_info['status']}",
            },
        )
    
    result = status_info["info"]
    
    return DocumentAnalysisSummary(
        document_id=result.get("document_id", job_id),
        title=result.get("title", "Untitled"),
        document_type=result.get("document_type", "unknown"),
        summary=result.get("summary", ""),
        key_points=result.get("key_points", []),
        remedies=result.get("remedies", []),
        deadlines=result.get("deadlines", []),
        obligations=result.get("obligations", []),
        confidence_score=result.get("confidence_score", 0.0),
        analysis_time_seconds=result.get("analysis_time_seconds", 0.0)
    )


@router.post(
    "/{job_id}/cancel",
    summary="Cancel analysis job"
)
async def cancel_analysis(
    job_id: str,
    current_user: CurrentUser = Depends(get_current_user)
) -> dict:
    """Cancel an analysis job"""
    
    success = TaskStatus.revoke_task(job_id)
    
    if success:
        return {"status": "cancelled", "job_id": job_id}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to cancel job"
        )
