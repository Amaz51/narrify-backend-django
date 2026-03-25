import logging

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger('narrify')

FASTAPI_URL = settings.FASTAPI_URL
TIMEOUT = settings.FASTAPI_TIMEOUT


def _proxy_to_fastapi(method: str, path: str, data=None, files=None, params=None):
    """
    Helper that forwards a request to the FastAPI backend and returns the response dict.
    Raises requests.RequestException on network failure.
    """
    url = f'{FASTAPI_URL}/{path.lstrip("/")}'
    response = requests.request(
        method,
        url,
        json=data if not files else None,
        data=data if files else None,
        files=files,
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# ─── Upload ──────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_pdf(request):
    """
    POST /api/gateway/upload/
    Forwards PDF file to FastAPI /upload endpoint.
    Returns: { file_id, filename, pages, chapters }
    """
    if 'file' not in request.FILES:
        return Response({'detail': 'No file provided.'}, status=status.HTTP_400_BAD_REQUEST)

    pdf_file = request.FILES['file']

    try:
        result = _proxy_to_fastapi(
            'POST',
            '/upload',
            files={'file': (pdf_file.name, pdf_file.read(), pdf_file.content_type)},
        )
        return Response(result)

    except requests.RequestException as exc:
        logger.error('FastAPI upload failed: %s', exc)
        return Response(
            {'detail': f'AI backend unavailable: {exc}'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


# ─── Processing ──────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def detect_speakers(request):
    """
    POST /api/gateway/process/
    Detects speakers and emotions via FastAPI /process/v2.
    Body: { file_id, source_language, target_language }
    """
    try:
        result = _proxy_to_fastapi('POST', '/process/v2', data=request.data)
        return Response(result)
    except requests.RequestException as exc:
        logger.error('FastAPI detect_speakers failed: %s', exc)
        return Response(
            {'detail': f'Processing failed: {exc}'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def processing_status(request, file_id: str):
    """
    GET /api/gateway/status/{file_id}/
    Returns processing status from FastAPI.
    """
    try:
        result = _proxy_to_fastapi('GET', f'/status/{file_id}')
        return Response(result)
    except requests.RequestException as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ─── Generation ───────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_audiobook(request):
    """
    POST /api/gateway/generate/
    Triggers TTS generation via FastAPI /generate/from-processing.
    """
    try:
        result = _proxy_to_fastapi('POST', '/generate/from-processing', data=request.data)
        return Response(result)
    except requests.RequestException as exc:
        logger.error('FastAPI generate failed: %s', exc)
        return Response(
            {'detail': f'Generation failed: {exc}'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def generation_status(request, file_id: str):
    """
    GET /api/gateway/generate/status/{file_id}/
    Returns generation progress from FastAPI.
    """
    try:
        result = _proxy_to_fastapi('GET', f'/generate/status/{file_id}')
        return Response(result)
    except requests.RequestException as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ─── Voice Cloning ────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clone_voice(request):
    """
    POST /api/gateway/voices/clone/
    Sends voice sample to FastAPI for embedding creation.
    """
    if 'audio' not in request.FILES:
        return Response({'detail': 'No audio file provided.'}, status=status.HTTP_400_BAD_REQUEST)

    audio = request.FILES['audio']
    voice_name = request.data.get('voice_name', 'Custom Voice')

    try:
        result = _proxy_to_fastapi(
            'POST',
            '/voices/clone',
            data={'voice_name': voice_name},
            files={'audio': (audio.name, audio.read(), audio.content_type)},
        )
        return Response(result)
    except requests.RequestException as exc:
        logger.error('FastAPI voice clone failed: %s', exc)
        return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ─── Health Check ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def fastapi_health(request):
    """
    GET /api/gateway/health/
    Returns FastAPI health status.
    """
    try:
        result = _proxy_to_fastapi('GET', '/health')
        return Response({'django': 'ok', 'fastapi': result})
    except requests.RequestException as exc:
        return Response(
            {'django': 'ok', 'fastapi': 'unreachable', 'detail': str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
