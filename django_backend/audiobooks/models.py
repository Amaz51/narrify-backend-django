from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Book(models.Model):
    """Core model representing an uploaded PDF and its audiobook state."""

    STATUS_UPLOADED = 'uploaded'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_UPLOADED, 'Uploaded'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]

    # Ownership
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='books')

    # Book metadata
    title = models.CharField(max_length=500)
    author = models.CharField(max_length=255, blank=True)

    # File storage
    pdf_file = models.FileField(upload_to='books/pdfs/', blank=True, null=True)
    file_size = models.BigIntegerField(default=0)   # bytes
    pages = models.IntegerField(default=0)

    # FastAPI integration
    file_id = models.CharField(max_length=200, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UPLOADED)
    celery_task_id = models.CharField(max_length=255, blank=True, null=True)
    error_message = models.TextField(blank=True)

    # Language settings
    source_language = models.CharField(max_length=100, default='english')
    target_language = models.CharField(max_length=100, default='english')

    # Generation settings
    emotion_intensity = models.FloatField(default=1.5)
    base_speed = models.FloatField(default=1.0)

    # Output stats
    total_chapters = models.IntegerField(default=0)
    total_segments = models.IntegerField(default=0)
    total_duration = models.FloatField(default=0.0)    # seconds
    generation_time = models.FloatField(default=0.0)   # seconds

    # Audio output path (relative to MEDIA_ROOT)
    output_audio_path = models.CharField(max_length=500, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['file_id']),
        ]

    def __str__(self):
        return f'{self.title} [{self.status}] — {self.user.username}'

    @property
    def duration_minutes(self):
        return round(self.total_duration / 60, 1) if self.total_duration else 0


class Chapter(models.Model):
    """A chapter within a book, maps to FastAPI chapter output."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='chapters')
    chapter_number = models.IntegerField()
    title = models.CharField(max_length=500, blank=True)
    content = models.TextField(blank=True)
    word_count = models.IntegerField(default=0)

    # Generated audio
    audio_file = models.FileField(upload_to='audiobooks/chapters/', blank=True, null=True)
    duration = models.FloatField(default=0.0)   # seconds

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['book', 'chapter_number']
        unique_together = [['book', 'chapter_number']]

    def __str__(self):
        return f'{self.book.title} — Ch.{self.chapter_number}'


class AudioSegment(models.Model):
    """A single speaker segment within a chapter."""

    SEGMENT_DIALOGUE = 'dialogue'
    SEGMENT_NARRATION = 'narration'
    SEGMENT_TYPES = [
        (SEGMENT_DIALOGUE, 'Dialogue'),
        (SEGMENT_NARRATION, 'Narration'),
    ]

    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name='segments')

    # Speaker
    speaker_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10)   # male / female / neutral
    voice_id = models.CharField(max_length=200, blank=True)

    # Content
    text = models.TextField()
    emotion = models.CharField(max_length=50, default='neutral')
    segment_type = models.CharField(max_length=20, choices=SEGMENT_TYPES, default=SEGMENT_NARRATION)

    # Audio
    audio_file = models.FileField(upload_to='audiobooks/segments/', blank=True, null=True)
    duration = models.FloatField(default=0.0)

    order = models.IntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['chapter', 'order']

    def __str__(self):
        return f'[{self.speaker_name}] {self.text[:60]}...'


class VoiceProfile(models.Model):
    """A custom cloned voice uploaded by a user."""

    GENDER_MALE = 'male'
    GENDER_FEMALE = 'female'
    GENDER_NEUTRAL = 'neutral'
    GENDER_CHOICES = [
        (GENDER_MALE, 'Male'),
        (GENDER_FEMALE, 'Female'),
        (GENDER_NEUTRAL, 'Neutral'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='voices')

    voice_id = models.CharField(max_length=200, unique=True, db_index=True)
    voice_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    language = models.CharField(max_length=100, default='english')

    # Audio sample (≥ 6 sec)
    sample_audio = models.FileField(upload_to='voices/samples/')
    embedding_file = models.FileField(upload_to='voices/embeddings/', blank=True, null=True)

    is_custom = models.BooleanField(default=True)
    is_public = models.BooleanField(default=False)   # allow sharing in future

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.voice_name} ({self.user.username}) — {self.gender}'
