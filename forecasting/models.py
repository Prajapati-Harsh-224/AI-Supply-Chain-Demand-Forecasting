from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    full_name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15)
    company_name = models.CharField(max_length=150)

    ROLE_CHOICES = (
    ("owner", "Owner"),
    ("admin", "Admin"),
)
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="planner")

    def __str__(self):
        return f"{self.username} ({self.company_name})"
    
