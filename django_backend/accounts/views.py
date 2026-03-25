import logging
import re

import requests
from django.contrib.auth import authenticate, get_user_model
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import (
    UserSerializer,
    UserUpdateSerializer,
    RegisterSerializer,
    ChangePasswordSerializer,
)

User = get_user_model()
logger = logging.getLogger('narrify')


class RegisterView(generics.CreateAPIView):
    """
    POST /api/auth/register/
    Create a new user account. Returns JWT tokens immediately after registration.
    """
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Issue tokens right away so the front-end doesn't need a second login call
        refresh = RefreshToken.for_user(user)
        logger.info('New user registered: %s', user.email)

        return Response(
            {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': UserSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """
    POST /api/auth/login/
    Accepts { username, password } — returns JWT access + refresh tokens.
    """
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')

    if not username or not password:
        return Response(
            {'detail': 'Username and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Allow login by email too
    if '@' in username:
        try:
            user_obj = User.objects.get(email=username)
            username = user_obj.username
        except User.DoesNotExist:
            pass

    user = authenticate(request, username=username, password=password)

    if user is None:
        logger.warning('Failed login attempt for: %s', username)
        return Response(
            {'detail': 'Invalid credentials.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        return Response(
            {'detail': 'Account is disabled. Contact support.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    refresh = RefreshToken.for_user(user)
    logger.info('User logged in: %s', user.email)

    return Response({
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        'user': UserSerializer(user).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    POST /api/auth/logout/
    Blacklists the provided refresh token.
    Body: { "refresh": "<token>" }
    """
    refresh_token = request.data.get('refresh')
    if not refresh_token:
        return Response(
            {'detail': 'Refresh token is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response({'detail': 'Successfully logged out.'})
    except Exception as exc:
        logger.warning('Logout error: %s', exc)
        return Response(
            {'detail': 'Invalid or already blacklisted token.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def profile_view(request):
    """
    GET  /api/auth/profile/  → Returns current user's profile.
    PATCH /api/auth/profile/ → Update full_name, phone_number, email.
    """
    if request.method == 'GET':
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    # PATCH
    serializer = UserUpdateSerializer(
        request.user,
        data=request.data,
        partial=True,
        context={'request': request},
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(UserSerializer(request.user).data)


@api_view(['POST'])
@permission_classes([AllowAny])
def google_auth_view(request):
    """
    POST /api/auth/google/
    Body: { "credential": "<google_access_token>" }
    Verifies the token with Google, finds or creates a user, returns JWT tokens.
    """
    access_token = request.data.get('credential', '').strip()
    if not access_token:
        return Response({'detail': 'Google credential is required.'}, status=status.HTTP_400_BAD_REQUEST)

    # Verify the access token with Google and retrieve user info
    try:
        resp = requests.get(
            'https://www.googleapis.com/oauth2/v3/userinfo',
            params={'access_token': access_token},
            timeout=10,
        )
        resp.raise_for_status()
        info = resp.json()
    except Exception as exc:
        logger.warning('Google token verification failed: %s', exc)
        return Response({'detail': 'Invalid Google token.'}, status=status.HTTP_401_UNAUTHORIZED)

    email = info.get('email')
    if not email:
        return Response({'detail': 'Could not retrieve email from Google.'}, status=status.HTTP_400_BAD_REQUEST)

    # Derive a username from the email prefix (alphanumeric + underscores only)
    base_username = re.sub(r'[^a-zA-Z0-9_]', '_', email.split('@')[0])
    full_name = info.get('name', '').strip()

    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            'username': _unique_username(base_username),
            'full_name': full_name,
            'is_active': True,
        },
    )

    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
        logger.info('New user created via Google OAuth: %s', email)
    else:
        logger.info('Existing user signed in via Google OAuth: %s', email)

    refresh = RefreshToken.for_user(user)
    return Response({
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        'user': UserSerializer(user).data,
    })


def _unique_username(base: str) -> str:
    """Return a username derived from base that doesn't already exist."""
    username = base
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f'{base}_{counter}'
        counter += 1
    return username


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password_view(request):
    """
    POST /api/auth/change-password/
    Body: { current_password, new_password }
    """
    serializer = ChangePasswordSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = request.user
    if not user.check_password(serializer.validated_data['current_password']):
        return Response(
            {'old_password': 'Incorrect password.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user.set_password(serializer.validated_data['new_password'])
    user.save()
    logger.info('Password changed for: %s', user.email)
    return Response({'detail': 'Password updated successfully.'})
