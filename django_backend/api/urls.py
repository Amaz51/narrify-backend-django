from django.urls import path
from . import views

urlpatterns = [
    # Upload
    path('upload/', views.upload_pdf, name='gateway-upload'),

    # Processing
    path('process/', views.detect_speakers, name='gateway-process'),
    path('status/<str:file_id>/', views.processing_status, name='gateway-status'),

    # Generation
    path('generate/', views.generate_audiobook, name='gateway-generate'),
    path('generate/status/<str:file_id>/', views.generation_status, name='gateway-gen-status'),

    # Voice cloning
    path('voices/clone/', views.clone_voice, name='gateway-voice-clone'),

    # Health
    path('health/', views.fastapi_health, name='gateway-health'),
]
