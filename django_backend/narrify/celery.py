import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'narrify.settings')

app = Celery('narrify')

# Read Celery config from Django settings using CELERY_ namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
