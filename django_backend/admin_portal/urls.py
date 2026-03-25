from django.urls import path
from . import views

urlpatterns = [
    path('stats/', views.stats_view, name='admin-stats'),
    path('users/', views.user_list_view, name='admin-user-list'),
    path('users/<int:user_id>/', views.user_detail_view, name='admin-user-detail'),
    path('books/', views.book_list_view, name='admin-book-list'),
    path('books/<int:book_id>/', views.book_detail_view, name='admin-book-detail'),
]
