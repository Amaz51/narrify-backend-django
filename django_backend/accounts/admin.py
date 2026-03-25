from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        'email', 'username', 'full_name', 'subscription_plan',
        'audiobooks_created', 'is_active', 'created_at',
    ]
    list_filter = ['subscription_plan', 'is_active', 'is_staff']
    search_fields = ['email', 'username', 'full_name']
    ordering = ['-created_at']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Narrify Profile', {
            'fields': ('full_name', 'phone_number', 'subscription_plan'),
        }),
        ('Usage Stats', {
            'fields': ('audiobooks_created', 'total_minutes_generated'),
            'classes': ('collapse',),
        }),
    )

    readonly_fields = ['created_at', 'updated_at', 'audiobooks_created', 'total_minutes_generated']
