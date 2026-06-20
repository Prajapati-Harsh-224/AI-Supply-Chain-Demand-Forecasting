from django.conf import settings
from django.db import models

class Store(models.Model):
    name = models.CharField(max_length=180)
    location = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (#{self.id})"


class OwnerProfile(models.Model):
    ROLE_CHOICES = (
        ("OWNER", "Store Owner"),
        ("ADMIN", "Admin"),
    )
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="OWNER")
    store = models.ForeignKey(Store, on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


class DataUpload(models.Model):
    UPLOAD_TYPE = (
        ("SALES", "Sales Data"),
        ("INVENTORY", "Inventory Data"),
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    upload_type = models.CharField(max_length=20, choices=UPLOAD_TYPE)
    filename = models.CharField(max_length=255)
    rows_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, default="SUCCESS")  # SUCCESS / FAILED
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SalesRecord(models.Model):
    """
    Minimal dataset for demo:
    date, product_sku, quantity
    """
    
    
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    date = models.DateField()
    product_sku = models.CharField(max_length=60)
    product_name = models.CharField(max_length=255, blank=True, null=True)
    quantity = models.IntegerField()

    class Meta:
        constraints = [
        models.UniqueConstraint(
            fields=["store", "date", "product_sku"],
            name="uniq_sales_store_date_sku",
        )
    ]
    indexes = [
        models.Index(fields=["store", "product_sku", "date"]),
    ]


class ForecastRecord(models.Model):
    """
    Predicted demand for a product on a date.
    """
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    date = models.DateField()
    product_sku = models.CharField(max_length=60)
    predicted_qty = models.FloatField()
    confidence = models.FloatField(default=0.75)  # 0..1
    
    
    class Meta:
        indexes = [
            models.Index(fields=["store", "date"]),
            models.Index(fields=["store", "product_sku"]),
        ]


class InventoryItem(models.Model):
    STATUS = (
        ("OK", "Healthy"),
        ("LOW", "Low Stock"),
        ("CRIT", "Critical"),
        ("OVER", "Overstock"),
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    product_sku = models.CharField(max_length=60)
    product_name = models.CharField(max_length=140)
    current_stock = models.IntegerField(default=0)
    reorder_point = models.IntegerField(default=0)
    safety_stock = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS, default="OK")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("store", "product_sku")


from django.db import models


class Alert(models.Model):
    SEVERITY_CHOICES = (
        ("INFO", "Info"),
        ("WARN", "Warning"),
        ("CRIT", "Critical"),
    )

    ALERT_TYPE_CHOICES = (
        ("LOW_STOCK", "Low Stock"),
        ("CRITICAL_LOW", "Critical Low Stock"),
        ("OVERSTOCK", "Overstock"),
    )

    store = models.ForeignKey(
    Store,
    on_delete=models.CASCADE,
    related_name="alerts",
    )
    
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPE_CHOICES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default="INFO")

    product_sku = models.CharField(max_length=60)
    product_name = models.CharField(max_length=150, blank=True, null=True)

    title = models.CharField(max_length=200)
    message = models.TextField(blank=True, null=True)

    current_stock = models.FloatField(default=0)
    threshold = models.FloatField(null=True, blank=True)

    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "alert_type"]),
            models.Index(fields=["store", "is_resolved"]),
            models.Index(fields=["store", "product_sku"]),
        ]
        
        constraints = [
        models.UniqueConstraint(
            fields=["store", "product_sku", "alert_type"],
            condition=models.Q(is_resolved=False),
            name="unique_active_alert_per_product"
        )
        ]

    def __str__(self):
        return self.title

class ReportJob(models.Model):
    """
    Scheduled reports (simple implementation).
    """
    REPORT_TYPES = (
        ("SYSTEM_OVERVIEW", "System Overview"),
        ("STORE_PERFORMANCE", "Store Performance"),
        ("FORECAST_ACCURACY", "Forecast Accuracy"),
        ("INVENTORY_OPT", "Inventory Optimization"),
        ("ALERT_SUMMARY", "Alert Summary"),
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    report_type = models.CharField(max_length=40, choices=REPORT_TYPES)
    title = models.CharField(max_length=180)
    schedule = models.CharField(max_length=40, default="MANUAL")  # MANUAL / DAILY / WEEKLY
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReportRun(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    job = models.ForeignKey(ReportJob, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=180)
    status = models.CharField(max_length=20, default="DONE")  # DONE/FAILED
    created_at = models.DateTimeField(auto_now_add=True)
    
from django.contrib.auth import get_user_model
User = get_user_model()
# from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone as dj_timezone


class UserProfile(models.Model):
    ROLE_CHOICES = (
        ("OWNER", "Store Owner"),
        ("MANAGER", "Manager"),
        ("ADMIN", "Admin"),
    )

    TIMEZONE_CHOICES = (
        ("Asia/Kolkata", "Asia/Kolkata"),
        ("UTC", "UTC"),
        ("America/New_York", "America/New_York"),
        ("Europe/London", "Europe/London"),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    store = models.ForeignKey("Store", on_delete=models.SET_NULL, null=True, blank=True)

    phone_number = models.CharField(max_length=20, blank=True)
    profile_photo = models.ImageField(upload_to="profile_photos/", blank=True, null=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="OWNER")
    timezone = models.CharField(max_length=64, choices=TIMEZONE_CHOICES, default="Asia/Kolkata")

    email_notifications = models.BooleanField(default=True)
    low_stock_alerts = models.BooleanField(default=True)
    overstock_alerts = models.BooleanField(default=True)
    forecast_alerts = models.BooleanField(default=True)
    two_factor_enabled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_active = models.DateTimeField(default=dj_timezone.now)

    def __str__(self):
        return f"{self.user.username} Profile"


class ActivityLog(models.Model):
    ACTIVITY_TYPES = (
        ("LOGIN", "Login"),
        ("UPLOAD", "Upload"),
        ("FORECAST", "Forecast"),
        ("REPORT", "Report"),
        ("SETTINGS_UPDATE", "Settings Update"),
        ("PROFILE_UPDATE", "Profile Update"),
        ("PASSWORD_CHANGE", "Password Change"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="activity_logs")
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_TYPES)
    description = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.user.username} - {self.activity_type}"
    
class ModelMetrics(models.Model):
    mae = models.FloatField()
    rmse = models.FloatField()
    r2 = models.FloatField()
    smape = models.FloatField()
    accuracy = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Metrics {self.created_at}"
    
class ForecastCounter(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)