from django.contrib.auth.models import AbstractUser
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models


class User(AbstractUser):
    account_key = models.CharField(max_length=64, primary_key=True)
    username = None
    email = models.EmailField(unique=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []


class Account(models.Model):
    key = models.CharField(max_length=64, primary_key=True)


class RelationUser(AbstractBaseUser):
    account = models.OneToOneField(Account, on_delete=models.CASCADE)
    USERNAME_FIELD = "account"
