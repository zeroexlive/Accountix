"""Custom user model — defined BEFORE the first migration (Sprint 01).

Only a UUID primary key is added over Django's AbstractUser in Sprint 01;
profile fields belong in later sprints to avoid migration churn here.
"""

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        db_table = "users_user"
