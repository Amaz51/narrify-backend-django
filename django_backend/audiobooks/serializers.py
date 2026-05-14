from rest_framework import serializers
from .models import Book, Chapter, AudioSegment, VoiceProfile


class AudioSegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioSegment
        fields = '__all__'


class ChapterSerializer(serializers.ModelSerializer):
    segments = AudioSegmentSerializer(many=True, read_only=True)
    duration_minutes = serializers.SerializerMethodField()
    primary_speaker = serializers.SerializerMethodField()
    speakers = serializers.SerializerMethodField()

    class Meta:
        model = Chapter
        fields = '__all__'

    def get_duration_minutes(self, obj):
        return round(obj.duration / 60, 1) if obj.duration else 0

    def get_primary_speaker(self, obj):
        from collections import Counter
        names = [seg.speaker_name for seg in obj.segments.all()]
        if not names:
            return "Narrator"
        return Counter(names).most_common(1)[0][0]

    def get_speakers(self, obj):
        from collections import Counter
        counts = Counter(seg.speaker_name for seg in obj.segments.all())
        return [{"name": name, "count": count} for name, count in counts.most_common()]


class BookSerializer(serializers.ModelSerializer):
    """Full serializer with nested chapters (used for retrieve/detail view)."""
    chapters = ChapterSerializer(many=True, read_only=True)
    duration_minutes = serializers.ReadOnlyField()
    username = serializers.ReadOnlyField(source='user.username')
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = '__all__'
        read_only_fields = [
            'user', 'file_id', 'celery_task_id',
            'total_chapters', 'error_message',
        ]

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


class BookUpdateSerializer(serializers.ModelSerializer):
    """Serializer for PATCH requests — allows updating title, author, status, audio fields."""

    class Meta:
        model = Book
        fields = [
            'title', 'author',
            'status', 'output_audio_path',
            'total_duration', 'total_segments', 'generation_time',
            'completed_at', 'base_speed', 'emotion_intensity', 'is_public',
        ]


class BookListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list/dashboard views."""
    duration_minutes = serializers.ReadOnlyField()
    thumbnail_url = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    chapter_titles = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            'id', 'title', 'author', 'status',
            'source_language', 'target_language',
            'total_chapters', 'total_duration', 'duration_minutes',
            'file_id', 'created_at', 'completed_at', 'output_audio_path',
            'thumbnail', 'thumbnail_url', 'full_name', 'is_public',
            'chapter_titles',
        ]

    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.thumbnail.url)
            return obj.thumbnail.url
        return None

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_chapter_titles(self, obj):
        return list(
            obj.chapters.order_by('chapter_number').values('chapter_number', 'title')
        )


class BookCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new book entry (after FastAPI upload). Allows setting initial status."""

    class Meta:
        model = Book
        fields = [
            'file_id', 'title', 'author',
            'file_size', 'pages',
            'source_language', 'target_language',
            'emotion_intensity', 'base_speed',
            'status', 'is_public',
        ]
        extra_kwargs = {
            'status': {'required': False},
            'is_public': {'required': False},
        }


class VoiceProfileSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source='user.username')
    is_owner = serializers.SerializerMethodField()

    class Meta:
        model = VoiceProfile
        fields = [
            'id', 'voice_id', 'voice_name', 'gender', 'language',
            'sample_audio', 'embedding_file', 'is_custom', 'is_public',
            'username', 'is_owner', 'created_at',
        ]
        read_only_fields = ['user', 'voice_id', 'embedding_file', 'username', 'is_owner', 'created_at']

    def get_is_owner(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            return obj.user_id == request.user.id
        return False
