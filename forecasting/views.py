from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from ownerpanel.models import Store, OwnerProfile
from django.contrib.auth import get_user_model
from .forms import CustomUserCreationForm
from ownerpanel.models import Store, SalesRecord, InventoryItem, Alert
from django.db.models import F, Q
import json
from ownerpanel.models import Store, InventoryItem, ModelMetrics
from django.db.models import Count
from datetime import date, timedelta
from django.db.models import  Min, Max, Sum

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import F
from ownerpanel.models import Store, InventoryItem, ForecastRecord, ModelMetrics

def compute_status(current_stock, reorder_point, safety_stock):
    current_stock = float(current_stock or 0)
    rp = float(reorder_point or 0)
    ss = float(safety_stock or 0)

    if current_stock <= ss or (rp > 0 and current_stock <= rp):
        return "LOW"
    elif rp > 0 and current_stock >= rp * 3:
        return "OVER"
    return "OK"
# Public Pages

def home(request):

    #  redirect based on role
    if request.user.is_authenticated:

        # ADMIN
        if request.user.is_staff or request.user.is_superuser:
            return redirect("admin_dashboard")

        # OWNER
        if hasattr(request.user, "ownerprofile") and request.user.ownerprofile.role == "OWNER":
            return redirect("/owner/")


    return render(request, "home.html")

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)

        if user.is_staff or user.is_superuser:
            messages.error(request, "Admin must login from admin panel.")
            return redirect("admin_login")

        
        if user is not None:
            login(request, user)
            messages.success(request, "Logged in successfully.")

            #  ROLE BASED REDIRECT
            if hasattr(user, "ownerprofile") and user.ownerprofile.role == "OWNER" and user.ownerprofile.store_id:
                return redirect("/owner/")


            
            return redirect("home")  

        messages.error(request, "Invalid username or password.")
        return redirect("login")

    return render(request, "login.html")


def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)

        if form.is_valid():
            user = form.save()

            
            full_name = form.cleaned_data.get("full_name", "")
            if full_name:
                parts = full_name.split(" ", 1)
                user.first_name = parts[0]
                user.last_name = parts[1] if len(parts) > 1 else ""
                user.save()

            
            store = Store.objects.create(
                name=form.cleaned_data.get("company_name"),
                location=form.cleaned_data.get("location")  # new field
            )

            
            OwnerProfile.objects.create(
                user=user,
                role="OWNER",
                store=store,
                phone=form.cleaned_data.get("phone")
            )

            messages.success(request, "Account created successfully. Please login.")
            return redirect("login")

        else:
            messages.error(request, "Please correct the errors and try again.")
    else:
        form = CustomUserCreationForm()

    return render(request, "register.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("home")



# Admin Panel Auth Helpers
def is_admin(user):
    # Admin = staff OR superuser
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("admin_login")
        if not is_admin(request.user):
            return HttpResponseForbidden("403 Forbidden: Admin only")
        return view_func(request, *args, **kwargs)
    return wrapper
 
# Admin Panel Pages

def admin_login(request):
    
    if is_admin(request.user):
        return redirect("admin_dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        user = authenticate(request, username=username, password=password)

       
        if user and (user.is_staff or user.is_superuser):
            login(request, user)
            return redirect("admin_dashboard")

        return render(request, "adminpanel/login.html", {"error": "Invalid admin credentials"})

    return render(request, "adminpanel/login.html")


def admin_logout(request):
    logout(request)
    return redirect("admin_login")


@login_required(login_url="/admin-panel/login/")
@admin_required
def admin_dashboard(request):

    # =========================
    # KPI 1: Total Stores
    # =========================
    total_stores = Store.objects.count()

    # =========================
    # KPI 2: Total Products
    # =========================
    total_products = InventoryItem.objects.count()

    # =========================
    # KPI 3: Active Alerts
    # =========================
    alerts = Alert.objects.filter(
        is_resolved=False
    ).count()

    # =========================
    # KPI 4: System Accuracy
    # =========================
    latest = ModelMetrics.objects.order_by("-created_at").first()

    if latest:
        accuracy = round(100 - latest.smape, 2)
    else:
        accuracy = 0

    # =========================
    # STORE-WISE ACCURACY
    # =========================
    store_accuracy = []
    stores = Store.objects.all()
    base_accuracy = accuracy if accuracy else 70

    for store in stores:
        total_items_store = InventoryItem.objects.filter(store=store).count()

        low_items = InventoryItem.objects.filter(
            store=store,
            status="LOW"
        ).count()
 
        over_items = InventoryItem.objects.filter(
            store=store,
            status="OVER"
        ).count()

        issue_ratio = 0

        if total_items_store > 0:
            issue_ratio = (low_items + over_items) / total_items_store

        store_acc = base_accuracy - (issue_ratio * 30)

        store_accuracy.append({
            "name": store.name,
            "accuracy": round(max(store_acc, 40), 2)
        })

    # =========================
    # STORE-WISE CONFIDENCE 
    # =========================
    store_confidence_data = []

    stores = Store.objects.all()
    base_accuracy = accuracy if accuracy else 70

    for store in stores:
        items = InventoryItem.objects.filter(store=store)

        total_items = items.count()
        low_count = 0
        over_count = 0

        for it in items:
            stock = float(it.current_stock or 0)
            reorder = float(it.reorder_point or 0)
            safety = float(it.safety_stock or 0)

            if not reorder or not safety:
                sales = SalesRecord.objects.filter(
                    store=store,
                    product_sku=it.product_sku
                )

                if sales.exists():
                    agg = sales.aggregate(
                        min_date=Min("date"),
                        max_date=Max("date"),
                        total=Sum("quantity")
                    )

                    if agg["min_date"] and agg["max_date"]:
                        days = (agg["max_date"] - agg["min_date"]).days + 1
                        total = agg["total"] or 0

                        avg_daily = total / days if days > 0 else 0

                        if not reorder:
                            reorder = int(avg_daily * 3)

                        if not safety:
                            safety = int(avg_daily * 1.5)

            status = compute_status(stock, reorder, safety)

            if status == "LOW":
                low_count += 1
            elif status == "OVER":
                over_count += 1

        issue_ratio = (low_count + over_count) / total_items if total_items else 0

        store_conf = base_accuracy - (issue_ratio * 30)

        store_confidence_data.append({
            "store": store.name,
            "confidence": round(max(store_conf, 40), 2)
        })


    # =========================
    # INVENTORY HEALTH (ALL STORES)
    # =========================
    total_items = InventoryItem.objects.count()

    items = InventoryItem.objects.all()

    healthy_count = 0
    low_count = 0
    over_count = 0

    for it in items:
        stock = float(it.current_stock or 0)
        reorder = float(it.reorder_point or 0)
        safety = float(it.safety_stock or 0)

        #  SAME AUTO CALCULATION
        if not reorder or not safety:
            sales = SalesRecord.objects.filter(
                store=it.store,
                product_sku=it.product_sku
            )

            if sales.exists():
                agg = sales.aggregate(
                    min_date=Min("date"),
                    max_date=Max("date"),
                    total=Sum("quantity")
                )

                if agg["min_date"] and agg["max_date"]:
                    days = (agg["max_date"] - agg["min_date"]).days + 1
                    total = agg["total"] or 0

                    avg_daily = total / days if days > 0 else 0

                    if not reorder:
                        reorder = int(avg_daily * 3)

                    if not safety:
                        safety = int(avg_daily * 1.5)

        status = compute_status(stock, reorder, safety)

        if status == "OK":
            healthy_count += 1
        elif status == "LOW":
            low_count += 1
        else:
            over_count += 1

    if total_items > 0:
        healthy_pct = round((healthy_count / total_items) * 100)
        low_pct = round((low_count / total_items) * 100)
        over_pct = 100 - healthy_pct - low_pct
    else:
        healthy_pct = low_pct = over_pct = 0

 
    
    # =========================
    # CONTEXT
    # =========================
    context = {
        "total_stores": total_stores,
        "total_products": total_products,
        "alerts": alerts,
        "accuracy": accuracy,

        # charts
        "store_accuracy": json.dumps(store_accuracy),
        "healthy_pct": healthy_pct,
        "low_pct": low_pct,
        "over_pct": over_pct,
        "inventory_data": json.dumps([healthy_pct, low_pct, over_pct]),
        "store_conf_labels": json.dumps([x["store"] for x in store_confidence_data]),
        "store_conf_values": json.dumps([x["confidence"] for x in store_confidence_data]),
        
        
    }

    return render(request, "adminpanel/dashboard.html", context)

@login_required(login_url="/admin-panel/login/")
@admin_required
def admin_stores(request):
    return render(request, "adminpanel/stores.html")

from django.http import JsonResponse
from django.contrib.auth import get_user_model

from django.http import JsonResponse
from django.db.models import Min, Max, Sum
@login_required(login_url="/admin-panel/login/")
@admin_required
def admin_stores_api(request):
    try:
        stores = Store.objects.all()
        data = []

        for store in stores:
            items = list(InventoryItem.objects.filter(store=store))

            total_items = len(items)

            healthy_count = 0

            #  Auto Reorder
            for it in items:
                stock = float(it.current_stock or 0)
                reorder = float(it.reorder_point or 0)
                safety = float(it.safety_stock or 0)

                
                if not reorder or not safety:
                    sales = SalesRecord.objects.filter(
                        store=store,
                        product_sku=it.product_sku
                    )

                    if sales.exists():
                        agg = sales.aggregate(
                            min_date=Min("date"),
                            max_date=Max("date"),
                            total=Sum("quantity")
                        )

                        if agg["min_date"] and agg["max_date"]:
                            days = (agg["max_date"] - agg["min_date"]).days + 1
                            total = agg["total"] or 0

                            avg_daily = total / days if days > 0 else 0

                            if not reorder:
                                reorder = int(avg_daily * 3)

                            if not safety:
                                safety = int(avg_daily * 1.5)

                
                status = compute_status(stock, reorder, safety)

                if status == "OK":
                    healthy_count += 1

            inventory_health = int((healthy_count / total_items) * 100) if total_items else 0

            # owner
            owner = OwnerProfile.objects.filter(store=store).first()
            owner_name = owner.user.username if owner else "N/A"

            data.append({
                "id": store.id,
                "name": store.name,
                "owner": owner_name,
                "location": store.location,
                "total_products": total_items,
                "inventory_health": inventory_health,
            })

        return JsonResponse({"stores": data})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required(login_url="/admin-panel/login/")
@admin_required
def admin_users(request):
    users = [
        {"name": "Owner 1", "email": "owner1@mail.com", "role": "OWNER", "status": "Active"},
        {"name": "Owner 2", "email": "owner2@mail.com", "role": "OWNER", "status": "Inactive"},
    ]
    return render(request, "adminpanel/users.html", {"users": users})

from ownerpanel.models import ModelMetrics

@login_required(login_url="/admin-panel/login/")
@admin_required
def admin_analytics(request):
    
    

    latest = ModelMetrics.objects.order_by("-created_at").first()

    if latest:
        
        accuracy = 100 - latest.smape

        
        if accuracy >= 75:
            confidence = "High"
        elif accuracy >= 60:
            confidence = "Reliable"
        else:
            confidence = "Moderate"

        context = {
            "mae": round(latest.mae, 2),
            "rmse": round(latest.rmse, 2),
            "accuracy": round(accuracy, 2),   
            "confidence": confidence,
        }
    else:
        context = {
            "mae": 0,
            "rmse": 0,
            "accuracy": 0,
            "confidence": "N/A",
        }

    return render(request, "adminpanel/analytics.html", context)