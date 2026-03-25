from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Extended User model for Narrify.
    Uses email as the primary identifier alongside username.
    """

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)

    # Subscription
    PLAN_FREE = 'free'
    PLAN_PRO = 'pro'
    PLAN_ENTERPRISE = 'enterprise'
    PLAN_CHOICES = [
        (PLAN_FREE, 'Free'),
        (PLAN_PRO, 'Pro'),
        (PLAN_ENTERPRISE, 'Enterprise'),
    ]
    subscription_plan = models.CharField(
        max_length=20,
        choices=PLAN_CHOICES,
        default=PLAN_FREE,
    )

    # Usage tracking (updated by Celery tasks)
    audiobooks_created = models.IntegerField(default=0)
    total_minutes_generated = models.FloatField(default=0.0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f'{self.email} ({self.get_full_name() or self.username})'

    @property
    def display_name(self):
        return self.full_name or self.username
