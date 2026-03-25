from django.contrib import admin
from .models import Book, Chapter, AudioSegment, VoiceProfile


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'status', 'source_language', 'target_language',
                    'total_duration', 'created_at']
    list_filter = ['status', 'source_language', 'target_language']
    search_fields = ['title', 'author', 'user__username', 'file_id']
    readonly_fields = ['file_id', 'celery_task_id', 'total_chapters',
                       'total_segments', 'total_duration', 'generation_time',
                       'completed_at', 'created_at', 'updated_at']
    ordering = ['-created_at']


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ['book', 'chapter_number', 'title', 'word_count', 'duration']
    list_filter = ['book__status']
    search_fields = ['book__title', 'title']


@admin.register(AudioSegment)
class AudioSegmentAdmin(admin.ModelAdmin):
    list_display = ['chapter', 'order', 'speaker_name', 'gender', 'emotion', 'segment_type']
    list_filter = ['gender', 'emotion', 'segment_type']
    search_fields = ['speaker_name', 'text']


@admin.register(VoiceProfile)
class VoiceProfileAdmin(admin.ModelAdmin):
    list_display = ['voice_name', 'user', 'gender', 'language', 'is_custom', 'created_at']
    list_filter = ['gender', 'language', 'is_custom', 'is_public']
    search_fields = ['voice_name', 'user__username']
