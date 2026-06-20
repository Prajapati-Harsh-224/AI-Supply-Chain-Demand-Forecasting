from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

app_name = "ownerpanel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("upload/", views.upload_data, name="upload"),
    path("forecast/", views.demand_forecast, name="forecast"),
    path("inventory/", views.inventory_status, name="inventory"),
    path('api/top-products/', views.top_products_api, name='top_products_api'),
    # Alerts
   path("alerts/", views.alerts_page, name="alerts"),
path("alerts/read/<int:alert_id>/", views.alert_read, name="alert_read"),
path("alerts/resolve/<int:alert_id>/", views.resolve_alert, name="resolve_alert"),
    path("upload-history/clear/", views.clear_upload_history, name="clear_upload_history"),
    path("alerts/", views.alerts_page, name="alerts_page"),

        # Reports
    path("reports/", views.reports_page, name="reports"),
    path("reports/download/store-performance/", views.download_store_performance, name="download_store_performance"),
    path("reports/download/inventory/", views.download_inventory, name="download_inventory"),
    
    # charts & exports
    path("api/demand-chart/", views.api_demand_chart, name="api_demand_chart"),
    
    path("profile/", views.profile, name="profile"),
path("profile/update/", views.update_profile, name="update_profile"),
path("profile/change-password/", views.change_password, name="change_password"),

path("profile/settings/", views.update_account_settings, name="update_account_settings"),
path("profile/activity/", views.activity_history, name="activity_history"),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)