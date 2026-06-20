from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    
      # ===== Admin Panel =====
    path("admin-panel/login/", views.admin_login, name="admin_login"),
    path("admin-panel/logout/", views.admin_logout, name="admin_logout"),

    path("admin-panel/dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin-panel/stores/", views.admin_stores, name="admin_stores"),
    
    path("admin-panel/analytics/", views.admin_analytics, name="admin_analytics"),
    
    path("admin-panel/users/", views.admin_users, name="admin_users"),
    
    

path("adminpanel/stores/", views.admin_stores, name="admin_stores"),
path("adminpanel/stores/api/", views.admin_stores_api, name="admin_stores_api"),
]