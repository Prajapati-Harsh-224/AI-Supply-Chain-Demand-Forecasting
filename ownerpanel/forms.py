from django import forms

class CSVUploadForm(forms.Form):
    file = forms.FileField()
    upload_type = forms.ChoiceField(choices=(("SALES","Sales Data"),("INVENTORY","Inventory Data")))

class SettingsForm(forms.Form):
    full_name = forms.CharField(required=False)
    phone = forms.CharField(required=False)
    email = forms.EmailField(required=False)

    notify_email = forms.BooleanField(required=False)
    notify_in_app = forms.BooleanField(required=False)

    current_password = forms.CharField(required=False, widget=forms.PasswordInput)
    new_password = forms.CharField(required=False, widget=forms.PasswordInput)
    confirm_password = forms.CharField(required=False, widget=forms.PasswordInput)
    
    import re
from django import forms
from django.contrib.auth import get_user_model
from .models import Store

User = get_user_model()


class OwnerUserForm(forms.ModelForm):
    full_name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Full name"})
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "10-digit phone"})
    )

    class Meta:
        model = User
        fields = ["email"]  # handle full_name separately
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email"}),
        }

    def __init__(self, *args, **kwargs):
        self.user_instance = kwargs.pop("user_instance", None)
        super().__init__(*args, **kwargs)

        # set initial full name
        if self.user_instance:
            fn = (self.user_instance.first_name or "").strip()
            ln = (self.user_instance.last_name or "").strip()
            self.fields["full_name"].initial = (fn + " " + ln).strip()
            # phone is in ownerprofile usually (set in view initial)

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise forms.ValidationError("Email is required.")
        qs = User.objects.filter(email__iexact=email)
        if self.user_instance:
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError("This email is already in use.")
        return email

    def clean_phone(self):
        phone = (self.cleaned_data.get("phone") or "").strip()
        if not phone:
            return phone
        if not re.fullmatch(r"\d{10}", phone):
            raise forms.ValidationError("Phone must be a 10-digit number.")
        return phone


class OwnerStoreForm(forms.ModelForm):
    class Meta:
        model = Store
        fields = ["name", "location"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Store name"}),
            "location": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Location (optional)"}),
        }


class OwnerPasswordForm(forms.Form):
    new_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "New password (min 8 chars)"})
    )
    confirm_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Confirm password"})
    )

    def clean_new_password(self):
        pw = (self.cleaned_data.get("new_password") or "")
        if len(pw) < 8:
            raise forms.ValidationError("Password must be at least 8 characters.")
        return pw

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("new_password")
        p2 = cleaned.get("confirm_password")
        if p1 and p2 and p1 != p2:
            self.add_error("confirm_password", "Passwords do not match.")
        return cleaned
    
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm
from .models import UserProfile


class ProfileForm(forms.ModelForm):
    full_name = forms.CharField(max_length=150, required=True, label="Full Name")
    email = forms.EmailField(required=True, label="Email Address")

    class Meta:
        model = UserProfile
        fields = [
            "phone_number",
            "timezone",
            "email_notifications",
            "low_stock_alerts",
            "overstock_alerts",
            "forecast_alerts",
        ]
        widgets = {
            "phone_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter phone number"}),
            "timezone": forms.Select(attrs={"class": "form-select"}),
            "email_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "low_stock_alerts": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "overstock_alerts": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "forecast_alerts": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        self.fields["full_name"].widget.attrs.update({"class": "form-control"})
        self.fields["email"].widget.attrs.update({"class": "form-control"})

        if user:
            self.fields["full_name"].initial = user.get_full_name()
            self.fields["email"].initial = user.email


class ProfilePhotoForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["profile_photo"]
        widgets = {
            "profile_photo": forms.FileInput(attrs={
                "class": "form-control",
                "accept": "image/*"
            })
        }

    def clean_profile_photo(self):
        photo = self.cleaned_data.get("profile_photo")
        if photo:
            if photo.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Image size must be less than 5 MB.")

            valid_types = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
            if hasattr(photo, "content_type") and photo.content_type not in valid_types:
                raise forms.ValidationError("Only JPG, PNG, and WEBP images are allowed.")
        return photo


class AccountSettingsForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "two_factor_enabled",
            "email_notifications",
            "low_stock_alerts",
            "overstock_alerts",
            "forecast_alerts",
            "timezone",
        ]
        widgets = {
            "two_factor_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "email_notifications": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "low_stock_alerts": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "overstock_alerts": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "forecast_alerts": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "timezone": forms.Select(attrs={"class": "form-select"}),
        }


class CustomPasswordChangeForm(DjangoPasswordChangeForm):
    old_password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))
    new_password1 = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))
    new_password2 = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))

    def clean_new_password1(self):
        password = self.cleaned_data.get("new_password1")
        if len(password) < 8:
            raise forms.ValidationError("Password must be at least 8 characters.")
        if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            raise forms.ValidationError("Password must contain both letters and numbers.")
        return password