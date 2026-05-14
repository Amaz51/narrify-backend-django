from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Read-only serializer for public user profile data."""
    profile_picture_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'full_name',
            'phone_number',
            'subscription_plan',
            'audiobooks_created',
            'total_minutes_generated',
            'created_at',
            'is_staff',
            'profile_picture',
            'profile_picture_url',
        ]
        read_only_fields = [
            'id',
            'audiobooks_created',
            'total_minutes_generated',
            'created_at',
            'is_staff',
        ]

    def get_profile_picture_url(self, obj):
        if obj.profile_picture:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_picture.url)
            return obj.profile_picture.url
        return None


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating profile fields including profile picture."""

    class Meta:
        model = User
        fields = ['full_name', 'phone_number', 'email', 'profile_picture']

    def validate_email(self, value):
        user = self.context['request'].user
        if User.objects.exclude(pk=user.pk).filter(email=value).exists():
            raise serializers.ValidationError('This email is already in use.')
        return value


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration with password confirmation."""

    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'},
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        label='Confirm password',
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password2', 'full_name']

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError(
                {'password': "Passwords don't match."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(**validated_data)
        return user


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password.

    Accepts { current_password, new_password } — matches the frontend API shape.
    The frontend validates new_password == confirm_password before sending.
    """

    current_password = serializers.CharField(required=True, style={'input_type': 'password'})
    new_password = serializers.CharField(
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'},
    )
