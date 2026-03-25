import logging
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum, Avg
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from audiobooks.models import Book
from .serializers import AdminUserSerializer, AdminUserUpdateSerializer, AdminBookSerializer

User = get_user_model()
logger = logging.getLogger('narrify')


@api_view(['GET'])
@permission_classes([IsAdminUser])
def stats_view(request):
    """
    GET /api/admin/stats/
    Returns platform-wide statistics for the admin dashboard.
    """
    now = timezone.now()
    last_30 = now - timedelta(days=30)
    last_7 = now - timedelta(days=7)

    total_users = User.objects.count()
    new_users_30d = User.objects.filter(created_at__gte=last_30).count()
    new_users_7d = User.objects.filter(created_at__gte=last_7).count()

    total_books = Book.objects.count()
    books_by_status = {
        s: Book.objects.filter(status=s).count()
        for s in [Book.STATUS_UPLOADED, Book.STATUS_PROCESSING, Book.STATUS_COMPLETED, Book.STATUS_FAILED]
    }
    completed_books = Book.objects.filter(status=Book.STATUS_COMPLETED)
    total_minutes = completed_books.aggregate(
        mins=Sum('total_duration')
    )['mins'] or 0
    avg_generation_time = completed_books.aggregate(
        avg=Avg('generation_time')
    )['avg'] or 0

    recent_books = Book.objects.select_related('user').order_by('-created_at')[:10]

    return Response({
        'users': {
            'total': total_users,
            'new_last_30_days': new_users_30d,
            'new_last_7_days': new_users_7d,
        },
        'books': {
            'total': total_books,
            'by_status': books_by_status,
            'total_minutes_generated': round(total_minutes / 60, 1),
            'avg_generation_time_seconds': round(avg_generation_time, 1),
        },
        'recent_books': AdminBookSerializer(recent_books, many=True).data,
    })


@api_view(['GET'])
@permission_classes([IsAdminUser])
def user_list_view(request):
    """
    GET /api/admin/users/?search=&subscription_plan=&is_active=&ordering=-created_at
    Returns paginated user list with optional filters.
    """
    qs = User.objects.all().order_by('-created_at')

    search = request.query_params.get('search', '').strip()
    if search:
        qs = qs.filter(
            username__icontains=search
        ) | qs.filter(
            email__icontains=search
        ) | qs.filter(
            full_name__icontains=search
        )

    plan = request.query_params.get('subscription_plan')
    if plan:
        qs = qs.filter(subscription_plan=plan)

    is_active = request.query_params.get('is_active')
    if is_active is not None:
        qs = qs.filter(is_active=(is_active.lower() == 'true'))

    ordering = request.query_params.get('ordering', '-created_at')
    allowed_orderings = {'created_at', '-created_at', 'username', '-username', 'email', '-email'}
    if ordering in allowed_orderings:
        qs = qs.order_by(ordering)

    serializer = AdminUserSerializer(qs, many=True)
    return Response({'count': qs.count(), 'results': serializer.data})


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def user_detail_view(request, user_id):
    """
    GET    /api/admin/users/<id>/  → full user detail
    PATCH  /api/admin/users/<id>/  → update is_active, is_staff, subscription_plan
    DELETE /api/admin/users/<id>/  → delete user
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(AdminUserSerializer(user).data)

    if request.method == 'PATCH':
        # Prevent self-demotion
        if request.user == user and request.data.get('is_staff') is False:
            return Response(
                {'detail': 'You cannot remove your own admin privileges.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('Admin %s updated user %s: %s', request.user.email, user.email, request.data)
        return Response(AdminUserSerializer(user).data)

    if request.method == 'DELETE':
        if request.user == user:
            return Response(
                {'detail': 'You cannot delete your own account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        email = user.email
        user.delete()
        logger.warning('Admin %s deleted user %s', request.user.email, email)
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def book_list_view(request):
    """
    GET /api/admin/books/?status=&user_id=&search=&ordering=-created_at
    Returns all books with optional filters.
    """
    qs = Book.objects.select_related('user').order_by('-created_at')

    search = request.query_params.get('search', '').strip()
    if search:
        qs = qs.filter(title__icontains=search) | qs.filter(user__username__icontains=search)

    book_status = request.query_params.get('status')
    if book_status:
        qs = qs.filter(status=book_status)

    user_id = request.query_params.get('user_id')
    if user_id:
        qs = qs.filter(user_id=user_id)

    ordering = request.query_params.get('ordering', '-created_at')
    allowed_orderings = {
        'created_at', '-created_at', 'title', '-title',
        'status', '-status', 'total_duration', '-total_duration',
    }
    if ordering in allowed_orderings:
        qs = qs.order_by(ordering)

    serializer = AdminBookSerializer(qs, many=True)
    return Response({'count': qs.count(), 'results': serializer.data})


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def book_detail_view(request, book_id):
    """
    GET    /api/admin/books/<id>/  → book detail
    PATCH  /api/admin/books/<id>/  → update status
    DELETE /api/admin/books/<id>/  → delete book
    """
    try:
        book = Book.objects.select_related('user').get(pk=book_id)
    except Book.DoesNotExist:
        return Response({'detail': 'Book not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(AdminBookSerializer(book).data)

    if request.method == 'PATCH':
        allowed_fields = {'status', 'title', 'author'}
        data = {k: v for k, v in request.data.items() if k in allowed_fields}
        serializer = AdminBookSerializer(book, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info('Admin %s updated book %s', request.user.email, book_id)
        return Response(AdminBookSerializer(book).data)

    if request.method == 'DELETE':
        book.delete()
        logger.warning('Admin %s deleted book %s', request.user.email, book_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
