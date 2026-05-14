import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('narrify')


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_audiobook_task(self, book_id: int):
    """
    Celery task: drives the full PDF → audiobook pipeline via FastAPI.

    Stages:
      10% ─ Book loaded, starting
      30% ─ Sent to FastAPI /process/v2 (speaker detection + emotion)
      60% ─ Sent to FastAPI /generate/from-processing (TTS)
      90% ─ Saving results to DB
     100% ─ Done
    """
    # Lazy import to avoid circular dependencies at module load time
    from .models import Book, Chapter, AudioSegment

    try:
        book = Book.objects.get(id=book_id)
    except Book.DoesNotExist:
        logger.error('process_audiobook_task: Book %s not found', book_id)
        return {'status': 'error', 'detail': 'Book not found'}

    book.status = Book.STATUS_PROCESSING
    book.error_message = ''
    book.save(update_fields=['status', 'error_message'])

    self.update_state(state='PROGRESS', meta={'progress': 10, 'stage': 'Starting'})
    logger.info('Processing book %s (file_id=%s)', book_id, book.file_id)

    fastapi_url = settings.FASTAPI_URL
    timeout = settings.FASTAPI_TIMEOUT

    try:
        # ── STAGE 1: Process PDF (speaker/emotion detection) ─────────────
        self.update_state(state='PROGRESS', meta={'progress': 25, 'stage': 'Detecting speakers'})

        process_resp = requests.post(
            f'{fastapi_url}/process/v2',
            json={
                'file_id': book.file_id,
                'source_language': book.source_language,
                'target_language': book.target_language,
                'detect_emotions': True,
            },
            timeout=timeout,
        )
        process_resp.raise_for_status()
        process_data = process_resp.json()

        self.update_state(state='PROGRESS', meta={'progress': 40, 'stage': 'Speaker detection done'})
        logger.info('FastAPI /process/v2 succeeded for book %s', book_id)

        # ── STAGE 2: Generate audiobook (TTS) ────────────────────────────
        self.update_state(state='PROGRESS', meta={'progress': 50, 'stage': 'Generating audio'})

        generate_resp = requests.post(
            f'{fastapi_url}/generate/from-processing',
            json={
                'file_id': book.file_id,
                'title': book.title,
                'chapters': process_data.get('chapters', []),
                'emotion_intensity': book.emotion_intensity,
                'base_speed': book.base_speed,
                'source_language': book.source_language,
                'target_language': book.target_language,
            },
            timeout=timeout,
        )
        generate_resp.raise_for_status()
        generate_data = generate_resp.json()

        self.update_state(state='PROGRESS', meta={'progress': 80, 'stage': 'Saving to database'})
        logger.info('FastAPI /generate succeeded for book %s', book_id)

        # ── STAGE 3: Persist results ──────────────────────────────────────
        book.total_segments = generate_data.get('segments_processed', 0)
        book.total_duration = generate_data.get('duration', 0.0)
        book.generation_time = generate_data.get('generation_time', 0.0)
        book.total_chapters = len(process_data.get('chapters', []))
        book.output_audio_path = generate_data.get('audio_url', '')
        book.status = Book.STATUS_COMPLETED
        book.completed_at = timezone.now()
        book.save()

        # Invalidate list cache so dashboard polling picks up the new status
        from django.core.cache import cache
        cache.delete(f'books_list_{book.user_id}')

        # Save chapter and segment data
        for chapter_data in process_data.get('chapters', []):
            chapter, _ = Chapter.objects.get_or_create(
                book=book,
                chapter_number=chapter_data.get('chapter_id', 0),
                defaults={
                    'title': chapter_data.get('chapter_title', ''),
                    'content': chapter_data.get('content', ''),
                    'word_count': sum(
                        len(s.get('text', '').split())
                        for s in chapter_data.get('segments', [])
                    ),
                },
            )
            # Create segments (bulk_create for performance)
            segment_objs = []
            for idx, seg in enumerate(chapter_data.get('segments', [])):
                segment_objs.append(AudioSegment(
                    chapter=chapter,
                    speaker_name=seg.get('speaker', 'Unknown'),
                    gender=seg.get('gender', 'neutral'),
                    voice_id=seg.get('voice_id', ''),
                    text=seg.get('text', ''),
                    emotion=seg.get('emotion', 'neutral'),
                    segment_type=seg.get('segment_type', 'narration'),
                    duration=seg.get('duration', 0.0),
                    order=idx,
                ))
            AudioSegment.objects.bulk_create(segment_objs, ignore_conflicts=True)

        # Update user stats
        user = book.user
        user.audiobooks_created = user.books.filter(status=Book.STATUS_COMPLETED).count()
        user.total_minutes_generated += book.total_duration / 60
        user.save(update_fields=['audiobooks_created', 'total_minutes_generated'])

        self.update_state(state='SUCCESS', meta={'progress': 100, 'stage': 'Complete'})
        logger.info('Book %s completed. Duration: %.1fs', book_id, book.total_duration)

        return {
            'status': 'completed',
            'book_id': book.id,
            'duration': book.total_duration,
            'segments': book.total_segments,
        }

    except requests.RequestException as exc:
        logger.error('FastAPI request failed for book %s: %s', book_id, exc)
        try:
            # Retry with exponential back-off
            raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
        except MaxRetriesExceededError:
            book.status = Book.STATUS_FAILED
            book.error_message = f'FastAPI unreachable after retries: {exc}'
            book.save(update_fields=['status', 'error_message'])
            from django.core.cache import cache
            cache.delete(f'books_list_{book.user_id}')
            return {'status': 'failed', 'detail': str(exc)}

    except Exception as exc:
        logger.exception('Unexpected error processing book %s', book_id)
        book.status = Book.STATUS_FAILED
        book.error_message = str(exc)
        book.save(update_fields=['status', 'error_message'])
        from django.core.cache import cache
        cache.delete(f'books_list_{book.user_id}')
        raise
