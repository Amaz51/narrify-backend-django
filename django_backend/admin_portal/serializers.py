from rest_framework import serializers
from django.contrib.auth import get_user_model
from audiobooks.models import Book

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
