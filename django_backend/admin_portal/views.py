import logging
import os
import tempfile

import requests as http_requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum, Avg, Q
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from audiobooks.models import Book, AudioEvaluation
from .serializers import AdminUserSerializer, AdminUserUpdateSerializer, AdminBookSerializer, AdminEvaluationSerializer

User = get_user_model()
logger = logging.getLogger('narrify')

# Resolve FastAPI base URL — the settings value may use the intended port (8001)
# but FastAPI actually runs on 8000; honour FASTAPI_URL from settings regardless.
FASTAPI_BASE = getattr(settings, 'FASTAPI_URL', 'http://localhost:8000/api').rstrip('/')


@api_view(['GET'])
@permission_classes([IsAdminUser])
def stats_view(request):
    """
    GET /api/admin/stats/
    Returns platform-wide statistics for the admin dashboard.
    """
    now = timezone.now()
    last_30 = now - timedelta(days=30)
    last_7 = now - timedelta(days=7)

    total_users = User.objects.count()
    new_users_30d = User.objects.filter(created_at__gte=last_30).count()
    new_users_7d = User.objects.filter(created_at__gte=last_7).count()

    total_books = Book.objects.count()
    books_by_status = {
        s: Book.objects.filter(status=s).count()
        for s in [Book.STATUS_UPLOADED, Book.STATUS_PROCESSING, Book.STATUS_COMPLETED, Book.STATUS_FAILED]
    }
    completed_books = Book.objects.filter(status=Book.STATUS_COMPLETED)
    total_minutes = completed_books.aggregate(
        mins=Sum('total_duration')
    )['mins'] or 0
    avg_generation_time = completed_books.aggregate(
        avg=Avg('generation_time')
    )['avg'] or 0

    recent_books = Book.objects.select_related('user').order_by('-created_at')[:10]

    return Response({
        'users': {
            'total': total_users,
            'new_last_30_days': new_users_30d,
            'new_last_7_days': new_users_7d,
        },
        'books': {
            'total': total_books,
            'by_status': books_by_status,
            'total_minutes_generated': round(total_minutes / 60, 1),
            'avg_generation_time_seconds': round(avg_generation_time, 1),
        },
        'recent_books': AdminBookSerializer(recent_books, many=True).data,
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def user_list_view(request):
    """
    GET /api/admin/users/?search=&subscription_plan=&is_active=&ordering=-created_at&page=1&page_size=10
    Returns paginated user list with optional filters.
    """
    qs = User.objects.all().order_by('-created_at')

    search = request.query_params.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search) |
            Q(full_name__icontains=search)
        ).distinct()

    plan = request.query_params.get('subscription_plan')
    if plan:
        qs = qs.filter(subscription_plan=plan)

    is_active = request.query_params.get('is_active')
    if is_active is not None:
        qs = qs.filter(is_active=(is_active.lower() == 'true'))

    ordering = request.query_params.get('ordering', '-created_at')
    allowed_orderings = {'created_at', '-created_at', 'username', '-username', 'email', '-email'}
    if ordering in allowed_orderings:
        qs = qs.order_by(ordering)

    total_count = qs.count()

    # Pagination
    try:
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(100, max(1, int(request.query_params.get('page_size', 10))))
    except (TypeError, ValueError):
        page, page_size = 1, 10

    offset = (page - 1) * page_size
    qs = qs[offset: offset + page_size]

    serializer = AdminUserSerializer(qs, many=True)
    return Response({'count': total_count, 'results': serializer.data})


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def user_detail_view(request, user_id):
    """
    GET    /api/admin/users/<id>/  → full user detail
    PATCH  /api/admin/users/<id>/  → update is_active, is_staff, subscription_plan
    DELETE /api/admin/users/<id>/  → delete user
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(AdminUserSerializer(user).data)

    if request.method == 'PATCH':
        # Prevent self-demotion
        if request.user == user and request.data.get('is_staff') is False:
            return Response(
                {'detail': 'You cannot remove your own admin privileges.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('Admin %s updated user %s: %s', request.user.email, user.email, request.data)
        return Response(AdminUserSerializer(serializer.instance).data)

    if request.method == 'DELETE':
        if request.user == user:
            return Response(
                {'detail': 'You cannot delete your own account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        email = user.email
        user.delete()
        logger.warning('Admin %s deleted user %s', request.user.email, email)
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def book_list_view(request):
    """
    GET /api/admin/books/?status=&user_id=&search=&ordering=-created_at&page=1&page_size=10
    Returns paginated book list with optional filters.
    """
    qs = Book.objects.select_related('user').order_by('-created_at')

    search = request.query_params.get('search', '').strip()
    if search:
        qs = qs.filter(title__icontains=search) | qs.filter(user__username__icontains=search)

    book_status = request.query_params.get('status')
    if book_status:
        qs = qs.filter(status=book_status)

    user_id = request.query_params.get('user_id')
    if user_id:
        qs = qs.filter(user_id=user_id)

    ordering = request.query_params.get('ordering', '-created_at')
    allowed_orderings = {
        'created_at', '-created_at', 'title', '-title',
        'status', '-status', 'total_duration', '-total_duration',
    }
    if ordering in allowed_orderings:
        qs = qs.order_by(ordering)

    total_count = qs.count()

    # Pagination
    try:
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(100, max(1, int(request.query_params.get('page_size', 10))))
    except (TypeError, ValueError):
        page, page_size = 1, 10

    offset = (page - 1) * page_size
    qs = qs[offset: offset + page_size]

    serializer = AdminBookSerializer(qs, many=True)
    return Response({'count': total_count, 'results': serializer.data})


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def book_detail_view(request, book_id):
    """
    GET    /api/admin/books/<id>/  → book detail
    PATCH  /api/admin/books/<id>/  → update status
    DELETE /api/admin/books/<id>/  → delete book
    """
    try:
        book = Book.objects.select_related('user').get(pk=book_id)
    except Book.DoesNotExist:
        return Response({'detail': 'Book not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(AdminBookSerializer(book).data)

    if request.method == 'PATCH':
        allowed_fields = {'status', 'title', 'author'}
        data = {k: v for k, v in request.data.items() if k in allowed_fields}
        serializer = AdminBookSerializer(book, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('Admin %s updated book %s', request.user.email, book_id)
        return Response(AdminBookSerializer(serializer.instance).data)

    if request.method == 'DELETE':
        book.delete()
        logger.warning('Admin %s deleted book %s', request.user.email, book_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ══════════════════════════════════════════════════════════════════════════════
# EVALUATION VIEWS
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_audio_bytes(audio_url: str) -> bytes:
    """Download audio from a URL and return raw bytes."""
    resp = http_requests.get(audio_url, timeout=60)
    resp.raise_for_status()
    return resp.content


def _fetch_audio_from_filesystem(output_audio_path: str) -> bytes:
    """Read audio directly from FastAPI's output directory (if accessible)."""
    fastapi_output_dir = getattr(settings, 'FASTAPI_OUTPUT_DIR', '')
    if not fastapi_output_dir:
        raise FileNotFoundError('FASTAPI_OUTPUT_DIR not configured')
    full_path = os.path.join(fastapi_output_dir, os.path.basename(output_audio_path))
    with open(full_path, 'rb') as f:
        return f.read()


@api_view(['POST'])
@permission_classes([IsAdminUser])
def evaluate_book_view(request, book_id):
    """
    POST /api/admin/books/<id>/evaluate/

    Triggers voice quality evaluation on a completed audiobook.
    Body (all optional):
      {
        "audio_url":        "http://localhost:8000/api/outputs/audiobook_xxx.mp3",
        "reference_url":    "http://...",   // for SECS
        "intended_emotion": "neutral",
        "original_text":    "The quick brown fox..."
      }

    - If audio_url is omitted, Django tries the book's output_audio_path via the
      filesystem (FASTAPI_OUTPUT_DIR) then via FastAPI's HTTP outputs endpoint.
    - Creates an AudioEvaluation record and returns the result.
    """
    try:
        book = Book.objects.get(pk=book_id)
    except Book.DoesNotExist:
        return Response({'detail': 'Book not found.'}, status=status.HTTP_404_NOT_FOUND)

    # ── Resolve audio ─────────────────────────────────────────────────────────
    audio_url = request.data.get('audio_url', '').strip()
    audio_bytes = None
    audio_filename = 'audio.mp3'

    if audio_url:
        try:
            audio_bytes = _fetch_audio_bytes(audio_url)
            audio_filename = os.path.basename(audio_url.split('?')[0]) or 'audio.mp3'
        except Exception as e:
            return Response(
                {'detail': f'Could not fetch audio from audio_url: {e}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
    elif book.output_audio_path:
        try:
            audio_bytes = _fetch_audio_from_filesystem(book.output_audio_path)
            audio_filename = os.path.basename(book.output_audio_path)
        except Exception:
            # Fallback: fetch via FastAPI HTTP
            fallback_url = f"{FASTAPI_BASE}/outputs/{os.path.basename(book.output_audio_path)}"
            try:
                audio_bytes = _fetch_audio_bytes(fallback_url)
                audio_url = fallback_url
                audio_filename = os.path.basename(book.output_audio_path)
            except Exception as e:
                return Response(
                    {'detail': f'Could not load audio for this book: {e}. Provide audio_url explicitly.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
    else:
        return Response(
            {'detail': 'No audio found for this book. Provide audio_url in the request body.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ── Optional reference audio (for SECS) ───────────────────────────────────
    reference_url = request.data.get('reference_url', '').strip()
    reference_bytes = None
    reference_filename = 'reference.wav'
    if reference_url:
        try:
            reference_bytes = _fetch_audio_bytes(reference_url)
            reference_filename = os.path.basename(reference_url.split('?')[0]) or 'reference.wav'
        except Exception as e:
            logger.warning('Could not fetch reference audio: %s', e)

    intended_emotion = request.data.get('intended_emotion', '').strip() or None
    original_text = request.data.get('original_text', '').strip() or None

    # ── Auto-fetch original text from FastAPI segment cache (for WER) ─────────
    if not original_text and book.file_id:
        try:
            text_resp = http_requests.get(
                f"{FASTAPI_BASE}/segments/{book.file_id}/text", timeout=10
            )
            if text_resp.ok:
                fetched = text_resp.json().get('text', '').strip()
                if fetched:
                    original_text = fetched
                    logger.info('Auto-fetched %d chars of original text for book %s', len(original_text), book_id)
        except Exception as e:
            logger.debug('Could not auto-fetch original text: %s', e)

    # ── Auto-fetch reference audio from user's voice profile (for SECS) ──────
    if not reference_bytes:
        try:
            from audiobooks.models import VoiceProfile
            profile = VoiceProfile.objects.filter(user=book.user).order_by('-created_at').first()
            if profile and profile.sample_audio:
                with open(profile.sample_audio.path, 'rb') as f:
                    reference_bytes = f.read()
                reference_filename = os.path.basename(profile.sample_audio.name)
                logger.info('Auto-using voice profile "%s" as SECS reference for book %s', profile.name, book_id)
        except Exception as e:
            logger.debug('Could not auto-fetch voice profile reference: %s', e)

    # ── Create pending evaluation record ─────────────────────────────────────
    evaluation = AudioEvaluation.objects.create(
        book=book,
        evaluated_by=request.user,
        audio_url=audio_url,
        intended_emotion=intended_emotion or '',
        status=AudioEvaluation.STATUS_PENDING,
    )

    # ── Call FastAPI /evaluate ────────────────────────────────────────────────
    try:
        files = {'audio_file': (audio_filename, audio_bytes, 'audio/mpeg')}
        if reference_bytes:
            files['reference_audio'] = (reference_filename, reference_bytes, 'audio/wav')

        data = {}
        if original_text:
            data['original_text'] = original_text
        if intended_emotion:
            data['intended_emotion'] = intended_emotion

        resp = http_requests.post(
            f"{FASTAPI_BASE}/evaluate",
            files=files,
            data=data,
            timeout=getattr(settings, 'FASTAPI_TIMEOUT', 300),
        )
        resp.raise_for_status()
        result = resp.json()

    except Exception as e:
        logger.error('FastAPI evaluate call failed for book %s: %s', book_id, e)
        evaluation.status = AudioEvaluation.STATUS_FAILED
        evaluation.error_message = str(e)
        evaluation.save()
        return Response(
            {'detail': f'Evaluation failed: {e}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # ── Persist results ───────────────────────────────────────────────────────
    intel = result.get('intelligibility') or {}
    natural = result.get('naturalness') or {}
    quality = result.get('audio_quality') or {}
    emotion = result.get('emotion') or {}
    similarity = result.get('speaker_similarity') or {}

    evaluation.wer = intel.get('wer')
    evaluation.cer = intel.get('cer')
    evaluation.transcribed_text = intel.get('transcribed_text') or ''
    evaluation.utmos_score = natural.get('utmos')
    evaluation.utmos_method = natural.get('method') or ''
    evaluation.snr_db = quality.get('snr_db')
    evaluation.detected_emotion = emotion.get('detected_emotion') or ''
    evaluation.emotion_match = emotion.get('emotion_match')
    evaluation.ser_confidence = emotion.get('confidence')
    evaluation.secs_score = similarity.get('secs')
    evaluation.overall_score = result.get('overall_score')
    evaluation.raw_results = result
    evaluation.status = AudioEvaluation.STATUS_COMPLETED
    evaluation.save()

    logger.info('Evaluation #%s completed for book %s (score=%s)', evaluation.pk, book_id, evaluation.overall_score)
    return Response(AdminEvaluationSerializer(evaluation).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def evaluation_list_view(request):
    """
    GET /api/admin/evaluations/?book_id=&page=1&page_size=10

    Returns paginated list of all evaluations, newest first.
    """
    qs = AudioEvaluation.objects.select_related('book', 'evaluated_by').order_by('-evaluated_at')

    book_id = request.query_params.get('book_id')
    if book_id:
        qs = qs.filter(book_id=book_id)

    total_count = qs.count()

    try:
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(100, max(1, int(request.query_params.get('page_size', 20))))
    except (TypeError, ValueError):
        page, page_size = 1, 20

    offset = (page - 1) * page_size
    qs = qs[offset: offset + page_size]

    return Response({'count': total_count, 'results': AdminEvaluationSerializer(qs, many=True).data})


@api_view(['GET', 'DELETE'])
@permission_classes([IsAdminUser])
def evaluation_detail_view(request, evaluation_id):
    """
    GET    /api/admin/evaluations/<id>/  — full evaluation detail (includes raw_results)
    DELETE /api/admin/evaluations/<id>/  — remove evaluation record
    """
    try:
        evaluation = AudioEvaluation.objects.select_related('book', 'evaluated_by').get(pk=evaluation_id)
    except AudioEvaluation.DoesNotExist:
        return Response({'detail': 'Evaluation not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(AdminEvaluationSerializer(evaluation).data)

    if request.method == 'DELETE':
        evaluation.delete()
        logger.info('Admin %s deleted evaluation %s', request.user.email, evaluation_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
