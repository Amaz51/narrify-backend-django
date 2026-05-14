import logging

from celery.result import AsyncResult
from django.core.cache import cache
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Book, Chapter, VoiceProfile
from .serializers import (
    BookSerializer,
    BookListSerializer,
    BookCreateSerializer,
    BookUpdateSerializer,
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
    PATCH  /api/audiobooks/books/{id}/      → update title/author/settings/status
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
        if self.action in ('update', 'partial_update'):
            return BookUpdateSerializer
        return BookSerializer

    DETAIL_ACTIONS = {'retrieve', 'update', 'partial_update', 'start_processing', 'task_status', 'retry_processing'}

    def get_queryset(self):
        user = self.request.user
        # For detail/write actions: scope strictly to the owner.
        # For list: allow viewing public books via ?visibility=public
        visibility = self.request.query_params.get('visibility', 'mine')
        if self.action == 'list' and visibility == 'public':
            from django.db.models import Q
            qs = Book.objects.filter(
                Q(user=user) | Q(is_public=True, status='completed')
            ).select_related('user')
        else:
            qs = Book.objects.filter(user=user).select_related('user')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        if self.action in self.DETAIL_ACTIONS:
            qs = qs.prefetch_related('chapters__segments')
        return qs

    def create(self, request, *args, **kwargs):
        """
        Upsert: if a Book with this file_id already exists for this user,
        update it and return it (200). Otherwise create a new one (201).
        Prevents the frontend from losing bookId when re-generating the same PDF.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_id = serializer.validated_data.get('file_id')
        existing = Book.objects.filter(file_id=file_id, user=request.user).first()

        if existing:
            for field, value in serializer.validated_data.items():
                setattr(existing, field, value)
            existing.save()
            self._invalidate_list_cache(request.user.id)
            out = BookListSerializer(existing, context={'request': request})
            return Response(out.data, status=status.HTTP_200_OK)

        self.perform_create(serializer)
        out = BookListSerializer(serializer.instance, context={'request': request})
        return Response(out.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        self._invalidate_list_cache(self.request.user.id)

    def list(self, request, *args, **kwargs):
        # No caching — dashboard polls every 5s and needs live status updates.
        return super().list(request, *args, **kwargs)

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

        if isinstance(info, dict):
            progress = info.get('progress', 0)
            stage = info.get('stage', '')
        else:
            progress = 0
            stage = ''

        if task.state == 'PENDING' and book.status == Book.STATUS_PROCESSING:
            progress = 5
            stage = 'Queued'

        return Response({
            'task_id': book.celery_task_id,
            'celery_state': task.state,
            'progress': progress,
            'stage': stage,
            'book_status': book.status,
        })

    @action(detail=True, methods=['post', 'delete'], url_path='thumbnail',
            parser_classes=[MultiPartParser, FormParser])
    def thumbnail(self, request, pk=None):
        """POST: upload/replace cover thumbnail. DELETE: remove it."""
        book = self.get_object()
        if request.method == 'DELETE':
            if book.thumbnail:
                book.thumbnail.delete(save=False)
                book.thumbnail = None
                book.save(update_fields=['thumbnail'])
                self._invalidate_list_cache(request.user.id)
            return Response({'status': 'removed'})

        # POST
        if 'thumbnail' not in request.FILES:
            return Response(
                {'detail': 'No thumbnail file provided.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if book.thumbnail:
            book.thumbnail.delete(save=False)
        book.thumbnail = request.FILES['thumbnail']
        book.save(update_fields=['thumbnail'])
        self._invalidate_list_cache(request.user.id)
        from .serializers import BookListSerializer
        return Response(BookListSerializer(book, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='force_reset')
    def force_reset(self, request, pk=None):
        """Reset a stuck processing book back to uploaded so it can be retried."""
        book = self.get_object()
        if book.status != Book.STATUS_PROCESSING:
            return Response(
                {'detail': 'Only processing books can be force reset.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        book.status = Book.STATUS_UPLOADED
        book.celery_task_id = None
        book.error_message = ''
        book.save(update_fields=['status', 'celery_task_id', 'error_message'])
        self._invalidate_list_cache(request.user.id)
        return Response({'status': 'uploaded'})

    @action(detail=True, methods=['post'], url_path='retry')
    def retry_processing(self, request, pk=None):
        """Retry a failed book or reprocess a completed book with missing audio."""
        book = self.get_object()
        missing_audio = book.status == Book.STATUS_COMPLETED and not book.output_audio_path
        if book.status != Book.STATUS_FAILED and not missing_audio:
            return Response(
                {'detail': 'Only failed books or completed books missing audio can be reprocessed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        task = process_audiobook_task.delay(book.id)
        book.celery_task_id = task.id
        book.status = Book.STATUS_PROCESSING
        book.error_message = ''
        book.save(update_fields=['celery_task_id', 'status', 'error_message'])
        return Response({'task_id': task.id, 'status': 'processing'})

    @action(detail=True, methods=['post'], url_path='save_chapters')
    def save_chapters(self, request, pk=None):
        """
        Save per-chapter audio paths returned by FastAPI generation.
        Expects: { "chapters": [{ "chapter_id": 1, "chapter_title": "...", "audio_url": "/api/outputs/...", "duration": 120 }] }
        Creates or updates Chapter records for the book.
        """
        book = self.get_object()
        chapters_data = request.data.get('chapters', [])
        if not chapters_data:
            return Response({'detail': 'No chapters provided.'}, status=status.HTTP_400_BAD_REQUEST)

        saved = []
        for ch in chapters_data:
            ch_num = ch.get('chapter_id', 1)
            ch_title = ch.get('chapter_title', f'Chapter {ch_num}')
            audio_url = ch.get('audio_url', '')
            duration = ch.get('duration', 0.0)

            chapter, _ = Chapter.objects.update_or_create(
                book=book,
                chapter_number=ch_num,
                defaults={
                    'title': ch_title,
                    'duration': duration,
                    # Store the relative audio URL in the content field for now
                    # (audio_file is a FileField so we use content to carry the URL)
                    'content': audio_url,
                }
            )
            saved.append({'chapter_number': ch_num, 'title': ch_title})

        book.total_chapters = len(saved)
        book.save(update_fields=['total_chapters'])
        self._invalidate_list_cache(book.user_id)

        return Response({'saved': len(saved), 'chapters': saved})

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        """
        Secure audio download — enforces ownership (or public access).
        Streams the file from the FastAPI output directory so the raw
        /outputs/{filename} FastAPI URL is never exposed to the client.
        """
        import os
        import mimetypes
        from pathlib import Path
        from django.http import FileResponse, Http404
        from django.conf import settings as django_settings
        from django.db.models import Q

        # Allow owner OR any user if book is public
        try:
            book = Book.objects.get(
                Q(pk=pk, user=request.user) | Q(pk=pk, is_public=True, status='completed')
            )
        except Book.DoesNotExist:
            raise Http404

        if not book.output_audio_path:
            return Response({'detail': 'Audio not yet generated.'}, status=status.HTTP_404_NOT_FOUND)

        # output_audio_path is stored as e.g. "/api/outputs/some_file.mp3"
        filename = os.path.basename(book.output_audio_path)
        # Prevent path traversal — only allow safe filenames
        if not filename or '/' in filename or '\\' in filename or filename.startswith('.'):
            return Response({'detail': 'Invalid audio path.'}, status=status.HTTP_400_BAD_REQUEST)

        output_dir = Path(getattr(django_settings, 'FASTAPI_OUTPUT_DIR', ''))
        file_path = output_dir / filename

        if not file_path.exists() or not file_path.is_file():
            return Response({'detail': 'Audio file not found on server.'}, status=status.HTTP_404_NOT_FOUND)

        # Build a friendly download filename
        title_slug = (
            (book.title or 'audiobook')
            .lower()
            .encode('ascii', errors='ignore')
            .decode()
        )
        import re
        title_slug = re.sub(r'[^a-z0-9]+', '_', title_slug).strip('_')[:50] or 'audiobook'
        lang = re.sub(r'[^a-z]', '', (book.target_language or book.source_language or 'en').lower())[:10]
        from datetime import date
        date_str = date.today().isoformat()
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp3'
        download_name = f'narrify_{title_slug}_{lang}_{date_str}.{ext}'

        mime_type, _ = mimetypes.guess_type(filename)
        response = FileResponse(
            open(file_path, 'rb'),
            content_type=mime_type or 'audio/mpeg',
        )
        response['Content-Disposition'] = f'attachment; filename="{download_name}"'
        return response


class VoiceProfileViewSet(viewsets.ModelViewSet):
    """
    CRUD for custom voice profiles.

    GET    /api/audiobooks/voices/                → list user's own voices + public voices
    GET    /api/audiobooks/voices/?scope=mine     → user's own voices only
    POST   /api/audiobooks/voices/                → create voice (upload sample)
    PATCH  /api/audiobooks/voices/{id}/           → update name/is_public (owner only)
    DELETE /api/audiobooks/voices/{id}/           → delete voice (owner only)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = VoiceProfileSerializer

    def get_queryset(self):
        from django.db.models import Q
        user = self.request.user
        scope = self.request.query_params.get('scope', 'all')
        if scope == 'mine':
            return VoiceProfile.objects.filter(user=user)
        # Default: own voices + public voices from others (for voice picker)
        return VoiceProfile.objects.filter(
            Q(user=user) | Q(is_public=True)
        ).select_related('user').distinct()

    def get_object(self):
        """Restrict write actions to the voice owner."""
        obj = super().get_object()
        if self.action in ('update', 'partial_update', 'destroy'):
            if obj.user != self.request.user:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied('You can only modify your own voices.')
        return obj

    def perform_create(self, serializer):
        import uuid
        voice_id = f'voice_{uuid.uuid4().hex[:12]}'
        serializer.save(user=self.request.user, voice_id=voice_id)
