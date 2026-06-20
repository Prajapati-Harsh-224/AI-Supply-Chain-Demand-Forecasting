from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    full_name = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "Enter Name"
        })
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "e.g. user@gmail.com"
        })
    )

    phone = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "Enter Number"
        })
    )

    company_name = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "e.g. ABC Traders"
        })
    )
    
    location = forms.CharField(
    max_length=255,
    widget=forms.TextInput(attrs={
        "class": "form-control",
        "placeholder": "Store location (City / Address)"
    })
)


    username = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "e.g. Enter Name"
        })
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "Enter password"
        })
    )

    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control form-control-lg",
            "placeholder": "Confirm password"
        })
    )
    
   

    class Meta:
        model = CustomUser
        fields = (
            "full_name",
            "email",
            "phone",
            "company_name",
            "username",
            "password1",
            "password2",
        )