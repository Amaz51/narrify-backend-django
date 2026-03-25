from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register('books', views.BookViewSet, basename='book')
router.register('voices', views.VoiceProfileViewSet, basename='voice')

urlpatterns = [
    path('', include(router.urls)),
]
