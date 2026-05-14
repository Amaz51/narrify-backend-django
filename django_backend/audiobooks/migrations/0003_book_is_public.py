from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audiobooks', '0002_book_thumbnail'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='is_public',
            field=models.BooleanField(default=False, help_text='If True, this audiobook is visible to all users in the public library.'),
        ),
    ]
