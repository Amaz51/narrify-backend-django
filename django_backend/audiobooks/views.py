import logging

from celery.result import AsyncResult
from django.core.cache import cache
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Book, VoiceProfile
from .serializers import (
    BookSerializer,
    BookListSerializer,
    BookCreateSerializer,
    VoiceProfileSerializer,
)
from .tasks import process_audiobook_task

logger = logging.getLogger('narrify')

CACHE_TTL = 60 * 5  # 5 minutes


class BookViewSet(viewsets.ModelViewSet):
    """
    CRUD for audiobooks.

    GET    /api/audiobooks/books/           → list user's books
    POST   /api/audiobooks/books/           → create book record (after FastAPI upload)
    GET    /api/audiobooks/books/{id}/      → book detail + chapters
    PATCH  /api/audiobooks/books/{id}/      → update title/author/settings
    DELETE /api/audiobooks/books/{id}/      → delete book
    POST   /api/audiobooks/books/{id}/start_processing/  → kick off Celery task
    GET    /api/audiobooks/books/{id}/task_status/       → Celery task progress
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return BookListSerializer
        if self.action == 'create':
            return BookCreateSerializer
        return BookSerializer

    DETAIL_ACTIONS = {'retrieve', 'update', 'partial_update', 'start_processing', 'task_status', 'retry_processing'}

    def get_queryset(self):
        qs = Book.objects.filter(user=self.request.user).select_related('user')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if self.action in self.DETAIL_ACTIONS:
            qs = qs.prefetch_related('chapters__segments')
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        self._invalidate_list_cache(self.request.user.id)

    def list(self, request, *args, **kwargs):
        cache_key = f'books_list_{request.user.id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, CACHE_TTL)
        return response

    def _invalidate_list_cache(self, user_id):
        cache.delete(f'books_list_{user_id}')

    def perform_update(self, serializer):
        serializer.save()
        self._invalidate_list_cache(self.request.user.id)

    def perform_destroy(self, instance):
        self._invalidate_list_cache(self.request.user.id)
        instance.delete()

    @action(detail=True, methods=['post'], url_path='start_processing')
    def start_processing(self, request, pk=None):
        """Enqueue a Celery task to process this audiobook via FastAPI."""
        book = self.get_object()

        if book.status in (Book.STATUS_PROCESSING, Book.STATUS_COMPLETED):
            return Response(
                {'detail': f'Book is already {book.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = process_audiobook_task.delay(book.id)
        book.celery_task_id = task.id
        book.status = Book.STATUS_PROCESSING
        book.save(update_fields=['celery_task_id', 'status'])
        self._invalidate_list_cache(request.user.id)

        logger.info('Started processing task %s for book %s', task.id, book.id)
        return Response({'task_id': task.id, 'status': 'processing'})

    @action(detail=True, methods=['get'], url_path='task_status')
    def task_status(self, request, pk=None):
        """Return real-time Celery task progress for this book."""
        book = self.get_object()

        if not book.celery_task_id:
            return Response({'status': book.status, 'progress': 0})

        task = AsyncResult(book.celery_task_id)
        info = task.info or {}

        return Response({
            'task_id': book.celery_task_id,
            'celery_state': task.state,
            'progress': info.get('progress', 0) if isinstance(info, dict) else 0,
            'stage': info.get('stage', '') if isinstance(info, dict) else '',
            'book_status': book.status,
        })

    @action(detail=True, methods=['post'], url_path='retry')
    def retry_processing(self, request, pk=None):
        """Retry a failed book."""
        book = self.get_object()
        if book.status != Book.STATUS_FAILED:
            return Response(
                {'detail': 'Only failed books can be retried.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        task = process_audiobook_task.delay(book.id)
        book.celery_task_id = task.id
        book.status = Book.STATUS_PROCESSING
        book.error_message = ''
        book.save(update_fields=['celery_task_id', 'status', 'error_message'])
        return Response({'task_id': task.id, 'status': 'processing'})


class VoiceProfileViewSet(viewsets.ModelViewSet):
    """
    CRUD for custom voice profiles.

    GET    /api/audiobooks/voices/      → list user's voices
    POST   /api/audiobooks/voices/      → create voice (upload sample)
    DELETE /api/audiobooks/voices/{id}/ → delete voice
    """
    permission_classes = [IsAuthenticated]
    serializer_class = VoiceProfileSerializer

    def get_queryset(self):
        return VoiceProfile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        import uuid
        voice_id = f'voice_{uuid.uuid4().hex[:12]}'
        serializer.save(user=self.request.user, voice_id=voice_id)
