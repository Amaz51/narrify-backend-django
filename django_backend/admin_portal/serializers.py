from rest_framework import serializers
from django.contrib.auth import get_user_model
from audiobooks.models import Book, AudioEvaluation

User = get_user_model()


class AdminUserSerializer(serializers.ModelSerializer):
    audiobook_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'full_name', 'phone_number',
            'subscription_plan', 'audiobooks_created', 'total_minutes_generated',
            'is_active', 'is_staff', 'created_at', 'audiobook_count',
        ]
        read_only_fields = ['id', 'created_at', 'audiobooks_created', 'total_minutes_generated']

    def get_audiobook_count(self, obj):
        return obj.books.count()


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['is_active', 'is_staff', 'subscription_plan']


class AdminBookSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = Book
        fields = [
            'id', 'title', 'author', 'status', 'source_language', 'target_language',
            'total_duration', 'total_chapters', 'total_segments', 'generation_time',
            'created_at', 'completed_at', 'username', 'user_email', 'user_id',
        ]
        read_only_fields = ['id', 'created_at', 'completed_at', 'username', 'user_email', 'user_id']


class AdminEvaluationSerializer(serializers.ModelSerializer):
    book_title = serializers.CharField(source='book.title', read_only=True)
    book_author = serializers.CharField(source='book.author', read_only=True)
    evaluated_by_username = serializers.CharField(source='evaluated_by.username', read_only=True, default=None)

    class Meta:
        model = AudioEvaluation
        fields = [
            'id', 'book_id', 'book_title', 'book_author',
            'evaluated_by_username', 'evaluated_at', 'status', 'error_message',
            'audio_url',
            # Intelligibility
            'wer', 'cer', 'transcribed_text',
            # Naturalness
            'utmos_score', 'utmos_method',
            # Audio quality
            'snr_db',
            # Emotion
            'intended_emotion', 'detected_emotion', 'emotion_match', 'ser_confidence',
            # Speaker similarity
            'secs_score',
            # Composite
            'overall_score',
            # Full payload (admin-only detail)
            'raw_results',
        ]
        read_only_fields = fields
