from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    # Django admin
    path('admin/', admin.site.urls),

    # Auth endpoints: /api/auth/register/, /api/auth/login/, etc.
    path('api/auth/', include('accounts.urls')),

    # Audiobook CRUD: /api/audiobooks/books/, /api/audiobooks/voices/
    path('api/audiobooks/', include('audiobooks.urls')),

    # API gateway to FastAPI: /api/gateway/...
    path('api/gateway/', include('api.urls')),

    # Admin portal: /api/admin/stats/, /api/admin/users/, /api/admin/books/
    path('api/admin/', include('admin_portal.urls')),

    # JWT token refresh (also available at /api/auth/token/refresh/)
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
