from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField("adresse e-mail", unique=True)

    def __str__(self) -> str:
        return self.email or self.username

