from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='auth-register'),
    path('login/', views.login_view, name='auth-login'),
    path('logout/', views.logout_view, name='auth-logout'),
    path('profile/', views.profile_view, name='auth-profile'),
    path('change-password/', views.change_password_view, name='auth-change-password'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('google/', views.google_auth_view, name='auth-google'),
]
