from rest_framework import serializers
from .models import Book, Chapter, AudioSegment, VoiceProfile


class AudioSegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioSegment
        fields = '__all__'


class ChapterSerializer(serializers.ModelSerializer):
    segments = AudioSegmentSerializer(many=True, read_only=True)
    duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model = Chapter
        fields = '__all__'

    def get_duration_minutes(self, obj):
        return round(obj.duration / 60, 1) if obj.duration else 0


class BookSerializer(serializers.ModelSerializer):
    """Full serializer with nested chapters (used for detail view)."""
    chapters = ChapterSerializer(many=True, read_only=True)
    duration_minutes = serializers.ReadOnlyField()
    username = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = Book
        fields = '__all__'
        read_only_fields = [
            'user', 'file_id', 'celery_task_id', 'status',
            'total_chapters', 'total_segments', 'total_duration',
            'generation_time', 'completed_at', 'error_message',
        ]


class BookListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list/dashboard views."""
    duration_minutes = serializers.ReadOnlyField()

    class Meta:
        model = Book
        fields = [
            'id', 'title', 'author', 'status',
            'source_language', 'target_language',
            'total_chapters', 'total_duration', 'duration_minutes',
            'file_id', 'created_at', 'completed_at',
        ]


class BookCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new book entry (after FastAPI upload)."""

    class Meta:
        model = Book
        fields = [
            'file_id', 'title', 'author',
            'file_size', 'pages',
            'source_language', 'target_language',
            'emotion_intensity', 'base_speed',
        ]

    def validate_file_id(self, value):
        if Book.objects.filter(file_id=value).exists():
            raise serializers.ValidationError('A book with this file_id already exists.')
        return value


class VoiceProfileSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = VoiceProfile
        fields = '__all__'
        read_only_fields = ['user', 'voice_id', 'embedding_file']
