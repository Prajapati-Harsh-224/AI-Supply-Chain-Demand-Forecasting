import csv
import io
import os
import re
import json
import difflib
import numpy as np
import pandas as pd
import joblib
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.db import transaction
from django.db.models import Sum, Max, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.timezone import now
from datetime import datetime, timedelta, date
from .models import InventoryItem, Store, DataUpload, SalesRecord, ForecastRecord, Alert
from .decorators import owner_required, get_owner_store
from .forms import CSVUploadForm
from django.db.models import Sum, Max, Count, Avg, Min
from django.core.paginator import Paginator
from django.db.models import Sum, Max, Count, Avg, Q
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.db.models import Q
from ownerpanel.models import ForecastRecord
from collections import OrderedDict
from .models import ReportRun
from .models import ForecastCounter
from .reports_generator import (
    calculate_store_performance_data,
    calculate_inventory_report_data,
    build_store_performance_pdf,
    build_inventory_pdf,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils import timezone
from django.contrib.auth import get_user_model
User = get_user_model()

from .models import UserProfile, ActivityLog, InventoryItem, ForecastRecord, ReportRun, DataUpload
from .forms import ProfileForm, ProfilePhotoForm, AccountSettingsForm, CustomPasswordChangeForm
# ---------------------------
# Load trained model once at startup
# ---------------------------
_BASE_DIR = settings.BASE_DIR
_MODEL_PATH = os.path.join(_BASE_DIR, "demand_forecast_model.pkl")
_FEATURE_PATH = os.path.join(_BASE_DIR, "feature_columns.json")

try:
    RF_MODEL = joblib.load(_MODEL_PATH)
    with open(_FEATURE_PATH, "r") as _f:
        FEATURE_COLS = json.load(_f)
except Exception as _e:
    import warnings
    warnings.warn(f"[demand_forecast] Could not load model: {_e}")
    RF_MODEL = None
    FEATURE_COLS = []


# ---------------------------
# Helpers
# ---------------------------
def _required_columns(upload_type):
    if upload_type == "SALES":
        return ["date", "product_sku", "quantity"]
    
    elif upload_type == "INVENTORY":
        
        return ["product_sku","product_name","current_stock"]

def _parse_csv(file) -> tuple[list, list]:
    """Returns (headers, rows_as_dict)"""
    raw = file.read().decode("utf-8-sig", errors="ignore")
    f = io.StringIO(raw)
    reader = csv.DictReader(f)
    headers = reader.fieldnames or []
    rows = [r for r in reader]
    return headers, rows


def _to_float(v, default=0.0):
    try:
        return float(str(v).strip())
    except Exception:
        return default


def _normalize_headers(headers):
    return [(h or "").lower().strip() for h in (headers or [])]


# ---------------------------
#  CSV column detection
# ---------------------------


_SALES_ALIASES = {
    "date":        ["date", "sale_date", "sales_date", "transaction_date", "order_date",
                    "bill_date", "created_at", "day", "period", "datetime", "week"],
    "product_sku": ["product_sku", "sku", "product_id", "item_id", "item_code", "itemcode",
                    "product_code", "code", "item_sku", "part_number", "part_no", "prodsku", "pid"],
    "product_name":["product_name", "item_name", "name", "product", "item",
                    "description", "prod_name", "prodname", "product_desc", "title"],
    "quantity":    ["quantity", "qty", "units", "units_sold", "sold_qty", "sales_qty",
                    "amount", "count", "sold", "volume", "demand", "num_units", "sales"],
}

_INVENTORY_ALIASES = {
    "product_sku": [
        "product_sku", "sku", "product_id", "item_id", "item_code",
        "product_code", "code", "item_sku", "part_number", "part_no",
        "prodsku", "pid"
    ],
    "product_name": [
        "product_name", "name", "product", "item_name", "item",
        "description", "prod_name", "prodname", "product_desc", "title"
    ],
    "current_stock": [
        "current_stock", "onhand", "on_hand", "stock", "inventory",
        "stock_current", "available", "available_stock", "qty_current",
        "balance", "in_stock", "current", "quantity", "qty"
    ],
    "reorder_point": [
        "reorder_point", "reorder", "reorder_level", "min_stock",
        "minimum_stock", "order_point", "trigger_point",
        "reorderpoint", "reorder_qty"
    ],
    "safety_stock": [
        "safety_stock", "safety", "buffer_stock", "min_safety",
        "safety_level", "safetystock", "buffer", "reserve", "safety_qty"
    ],
}


def _norm_key(h):
    """Normalize a header to lowercase-alphanumeric-underscore for comparison."""
    return re.sub(r'[^a-z0-9]+', '_', (h or '').lower().strip()).strip('_')


def _detect_column_mapping(raw_headers, alias_map, required_cols):
    """
    Map each standard column name to the actual CSV header.
    Steps: 1) exact normalized alias match  2) difflib fuzzy match.
    Returns (mapping {std_name: csv_header}, missing [std_names]).
    """
    norm_to_raw = {_norm_key(h): h for h in raw_headers if h}  # normkey -> original header
    norm_keys   = list(norm_to_raw.keys())
    mapping = {}
    missing = []

    for std_name, aliases in alias_map.items():
        found = None
        # 1) match against all aliases (normalized)
        for alias in aliases:
            nk = _norm_key(alias)
            if nk in norm_to_raw:
                found = norm_to_raw[nk]
                break
        # 2) fuzzy fallback
        if not found:
            close = difflib.get_close_matches(_norm_key(std_name), norm_keys, n=1, cutoff=0.75)
            if close:
                found = norm_to_raw[close[0]]
        if found:
            mapping[std_name] = found
        elif std_name in required_cols:
            missing.append(std_name)

    return mapping, missing


def _remap_rows(rows, mapping):
    """
    Rename every row's keys from original CSV headers → standard internal names.
    Also normalizes all keys (lowercase strip) so existing access like r['date'] still works.
    """
    reverse = {v: k for k, v in mapping.items()}  
    result = []
    for row in rows:
        new_row = {}
        for k, v in row.items():
            k_clean = (k or '').strip()
            std = reverse.get(k_clean, k_clean.lower())  # remap or just normalize
            new_row[std] = (v or '').strip()
        result.append(new_row)
    return result


# ---------------------------
# Pages
# ---------------------------
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Avg
from ownerpanel.models import InventoryItem, Alert, ForecastRecord
from .decorators import owner_required, get_owner_store

@login_required
@owner_required
def dashboard(request):
    store = get_owner_store(request)
    
    # -----------------------------
    # Inventory data
    # -----------------------------
    items = list(InventoryItem.objects.filter(store=store).order_by("-updated_at"))
    total_products = len(items)

    def compute_status(current_stock, reorder_point, safety_stock):
        stock = float(current_stock or 0)
        rp = float(reorder_point or 0)
        ss = float(safety_stock or 0)

        
        if stock <= ss or (rp > 0 and stock <= rp):
            return "LOW"
        elif rp > 0 and stock >= rp * 3:
            return "OVER"
        return "OK"

    from django.db.models import Min, Max, Sum

    for it in items:

        stock = float(it.current_stock or 0)
        reorder = float(it.reorder_point or 0)
        safety = float(it.safety_stock or 0)

        # AUTO CALCULATE 
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

        
        it.computed_status = compute_status(stock, reorder, safety)

    healthy_count = sum(1 for it in items if it.computed_status == "OK")
    low_count = sum(1 for it in items if it.computed_status == "LOW")
    overstock_count = sum(1 for it in items if it.computed_status == "OVER")

    at_risk_count = low_count + overstock_count
    inventory_health_pct = int((healthy_count / total_products) * 100) if total_products else 0

    # -----------------------------
    # Alerts data
    # -----------------------------
    inventory_skus = [it.product_sku for it in items]

    alerts_qs = Alert.objects.filter(
        store=store,
        product_sku__in=inventory_skus,
        is_resolved=False
    ).order_by("-created_at")

    active_alerts = alerts_qs.count()
    low_alert_count = alerts_qs.filter(alert_type="LOW_STOCK").count()
    overstock_alert_count = alerts_qs.filter(alert_type="OVERSTOCK").count()

    # -----------------------------
    # Forecast count
    # -----------------------------
    forecast_generated = ForecastCounter.objects.filter(store=store).count()

# -----------------------------
# Top Products Chart
# -----------------------------
    from django.utils.timezone import now
    from django.db.models import Sum, Count, F, FloatField, ExpressionWrapper
    from datetime import timedelta
    from django.db.models import Min, Max
    from django.db.models import Avg
    from collections import defaultdict
    
    date_range = ForecastRecord.objects.filter(store=store).aggregate(
    start=Min("date"),
    end=Max("date")
    )

    forecast_qs = ForecastRecord.objects.filter(
    store=store,
    date__range=(date_range["start"], date_range["end"])
    )

    
    daily_data = (
    forecast_qs
    .values("product_sku", "date")
    .annotate(daily_qty=Avg("predicted_qty"))
)

    product_data = defaultdict(list)

    for row in daily_data:
        product_data[row["product_sku"]].append(row["daily_qty"])

    final = []

    for sku, values in product_data.items():
        total = sum(values)
        days = len(values)

        normalized = (total / days) * 7 if days else 0

        final.append({
            "sku": sku,
            "value": round(normalized, 2)
        })

    # sort top 5
    final = sorted(final, key=lambda x: x["value"], reverse=True)[:5]

    chart_labels = [item["sku"] for item in final]
    chart_values = [item["value"] for item in final]
    
    # -----------------------------
    # Donut chart data
    # -----------------------------
    distribution_labels = ["Healthy Stock", "Low Stock", "Overstock"]
    distribution_values = [healthy_count, low_count, overstock_count]

    context = {
        "store": store,

        "total_products": total_products,
        "active_alerts": active_alerts,
        "forecast_generated": forecast_generated,

        "healthy_count": healthy_count,
        "low_count": low_count,
        "overstock_count": overstock_count,
        "at_risk_count": at_risk_count,
        "inventory_health_pct": inventory_health_pct,

        "low_alert_count": low_alert_count,
        "overstock_alert_count": overstock_alert_count,

        "chart_labels": chart_labels,
        "chart_values": chart_values,

        "distribution_labels": distribution_labels,
        "distribution_values": distribution_values,
    }

    return render(request, "ownerpanel/dashboard.html", context)

from django.http import JsonResponse
from datetime import timedelta
from django.db.models import Avg
from collections import defaultdict
from django.utils.timezone import now
from django.db.models import Min, Max
from django.db.models import Sum, Count, F, FloatField, ExpressionWrapper

def top_products_api(request):
    store = get_owner_store(request)

    # full date range 
    date_range = ForecastRecord.objects.filter(store=store).aggregate(
        start=Min("date"),
        end=Max("date")
    )

    
    daily_data = (
        ForecastRecord.objects
        .filter(store=store, date__range=(date_range["start"], date_range["end"]))
        .values("product_sku", "date")
        .annotate(daily_qty=Avg("predicted_qty"))   # key fix
    )

    product_data = defaultdict(list)

    for row in daily_data:
        product_data[row["product_sku"]].append(row["daily_qty"])

    final = []

    for sku, values in product_data.items():
        total = sum(values)
        days = len(values)

        normalized = (total / days) * 7 if days else 0

        final.append({
            "sku": sku,
            "value": round(normalized, 2)
        })

    # top 5
    final = sorted(final, key=lambda x: x["value"], reverse=True)[:5]

    labels = []
    values = []

    for d in final:
        sku = d["sku"]

        item = InventoryItem.objects.filter(store=store, product_sku=sku).first()
        name = item.product_name if item else sku

        labels.append(name)
        values.append(d["value"])

    return JsonResponse({
        "labels": labels,
        "values": values
    })

@owner_required
def upload_data(request):
    store = get_owner_store(request)
    form = CSVUploadForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        upload_type = form.cleaned_data["upload_type"]
        f = form.cleaned_data["file"]

        headers, rows = _parse_csv(f)

        # ---- Flexible column detection ----
        alias_map   = _SALES_ALIASES if upload_type == "SALES" else _INVENTORY_ALIASES
        required    = set(_required_columns(upload_type))
        mapping, missing = _detect_column_mapping(headers, alias_map, required)

        if missing:
            friendly = ", ".join(f'"{c}"' for c in missing)
            msg = (
                f"Could not detect required column(s): {friendly}. "
                f"Your file has: {', '.join(headers or ['(none)'])}. "
                f"Please rename or check your headers."
            )
            messages.error(request, msg)
            DataUpload.objects.create(
                store=store,
                uploaded_by=request.user,
                upload_type=upload_type,
                filename=f.name,
                rows_count=0,
                status="FAILED",
                message=msg[:500],
            )
            return redirect("ownerpanel:upload")

        # Remap rows
        clean_rows = _remap_rows(rows, mapping)

        # ================= SALES =================
        if upload_type == "SALES":
            try:
                # Build a DataFrame from clean_rows for robust parsing
                df = pd.DataFrame(clean_rows)

                # Debug: show what columns were detected
                print(f"[SALES UPLOAD] Columns in remapped df: {list(df.columns)}")

                # Strip whitespace from key columns
                df["date"]        = df["date"].astype(str).str.strip()
                df["product_sku"] = df["product_sku"].astype(str).str.strip()

                # Try normal parsing first
                df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")

                # If too many invalid → try dayfirst format
                if df["date_parsed"].isna().mean() > 0.3:
                    df["date_parsed"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")

                # Assign final
                df["date"] = df["date_parsed"].dt.date
                df.drop(columns=["date_parsed"], inplace=True)

                # Robust numeric quantity
                df["quantity"] = df["quantity"].astype(str).str.strip()
                df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

                # Debug info
                nat_count = df["date"].isna().sum()
                nan_qty   = df["quantity"].isna().sum()
                print(f"[SALES UPLOAD] Total rows: {len(df)}, NaT dates: {nat_count}, NaN qty: {nan_qty}")
                print(f"[SALES UPLOAD] Sample parsed dates: {df['date'].dropna().head(5).tolist()}")
                
                if nat_count > 0:
                    messages.warning(request, f"{nat_count} row(s) skipped due to invalid date format")
                
                if nan_qty > 0:
                    messages.warning(request, f"{nan_qty} row(s) skipped due to invalid quantity format")
               

                # Drop rows with missing date, empty SKU, or missing quantity
                before = len(df)
                df = df[
                    df["date"].notna() &
                    df["product_sku"].notna() &
                    (df["product_sku"] != "") &
                    df["quantity"].notna()
                ]
                dropped = before - len(df)
                if dropped:
                    print(f"[SALES UPLOAD] Dropped {dropped} invalid row(s).")

                if df.empty:
                    msg = (
                        f"No valid rows found after parsing. "
                        f"{nat_count} row(s) had unparseable dates, "
                        f"{nan_qty} row(s) had invalid quantities. "
                        f"Check your date format (e.g. YYYY-MM-DD or DD/MM/YYYY)."
                    )
                    messages.error(request, msg)
                    DataUpload.objects.create(
                        store=store,
                        uploaded_by=request.user,
                        upload_type="SALES",
                        filename=f.name,
                        rows_count=0,
                        status="FAILED",
                        message=msg[:500],
                    )
                    return redirect("ownerpanel:upload")

                # Build SalesRecord objects
                to_create = []
                seen = set()
                for _, row in df.iterrows():
                    d    = row["date"]
                    sku  = str(row["product_sku"]).strip()
                    qty  = float(row["quantity"])
                    name = str(row.get("product_name", "") or "").strip() or None
                    key  = (d, sku)
                    if key in seen:
                        continue
                    seen.add(key)
                    to_create.append(SalesRecord(
                        store=store, date=d, product_sku=sku,
                        quantity=qty, product_name=name,
                    ))

                # Upsert logic
                keys  = {(obj.date, obj.product_sku) for obj in to_create}
                dates = {d for d, _ in keys}
                skus  = {s for _, s in keys}

                existing     = SalesRecord.objects.filter(store=store, date__in=list(dates), product_sku__in=list(skus))
                existing_map = {(e.date, e.product_sku): e for e in existing}

                to_insert, to_update = [], []
                for obj in to_create:
                    k = (obj.date, obj.product_sku)
                    if k in existing_map:
                        existing_map[k].quantity     = obj.quantity
                        existing_map[k].product_name = obj.product_name
                        to_update.append(existing_map[k])
                    else:
                        to_insert.append(obj)

                with transaction.atomic():
                    if to_insert:
                        SalesRecord.objects.bulk_create(to_insert)
                    if to_update:
                        SalesRecord.objects.bulk_update(to_update, ["quantity", "product_name"])

                msg = f"Inserted: {len(to_insert)}, Updated: {len(to_update)}"
                if dropped:
                    msg += f" ({dropped} row(s) skipped — invalid date or quantity)"
                messages.success(request, msg)
                DataUpload.objects.create(
                    store=store,
                    uploaded_by=request.user,
                    upload_type="SALES",
                    filename=f.name,
                    rows_count=len(to_insert) + len(to_update),
                    status="SUCCESS",
                    message=msg,
                )

            except Exception as e:
                import traceback
                print(f"[SALES UPLOAD] Exception: {traceback.format_exc()}")
                DataUpload.objects.create(
                    store=store,
                    uploaded_by=request.user,
                    upload_type="SALES",
                    filename=f.name,
                    status="FAILED",
                    message=str(e)[:500],
                )
                messages.error(request, f"Sales upload failed: {e}")

        # ================= INVENTORY =================
        else:
            try:
                created = 0
                for r in clean_rows:
                    InventoryItem.objects.update_or_create(
                        store=store,
                        product_sku=r["product_sku"],
                        defaults={
                            "product_name": r.get("product_name", r["product_sku"]),
                            "current_stock": _to_float(r["current_stock"]),
                            "reorder_point": _to_float(r.get("reorder_point") or 0),
                            "safety_stock": _to_float(r.get("safety_stock") or 0),
                        },
                    )
                    created += 1

                messages.success(request, f"Inventory rows processed: {created}")
                DataUpload.objects.create(
                    store=store,
                    uploaded_by=request.user,
                    upload_type="INVENTORY",
                    filename=f.name,
                    rows_count=created,
                    status="SUCCESS",
                    message="Uploaded successfully",
                )
                
                sync_inventory_alerts(store)
                
            except Exception as e:
                DataUpload.objects.create(
                    store=store,
                    uploaded_by=request.user,
                    upload_type="INVENTORY",
                    filename=f.name,
                    status="FAILED",
                    message=str(e)[:500],
                )
                messages.error(request, f"Inventory upload failed: {e}")

        return redirect("ownerpanel:upload")

    uploads = DataUpload.objects.filter(store=store).order_by("-created_at")[:20]

    return render(request, "ownerpanel/upload.html", {    "store": store,"form": form, "uploads": uploads })
    
    
    
def _build_feature_row(series, next_date, product_id, store_id_enc, last_price=0.0):
    s = np.array(series, dtype=float)
    mean_fallback = float(np.mean(s)) if len(s) else 0.0

    def safe_lag(k):
        return float(s[-k]) if len(s) >= k else mean_fallback

    def safe_roll(k):
        return float(np.mean(s[-k:])) if len(s) >= k else mean_fallback

    return {
        "product_id": product_id,
        "store_id_enc": store_id_enc,
        "dayofweek": next_date.weekday(),
        "month": next_date.month,
        "day": next_date.day,
        "weekofyear": int(next_date.isocalendar()[1]),
        "is_weekend": int(next_date.weekday() >= 5),
        "promo_flag": 0,
        "price": float(last_price),
        "lag_1": safe_lag(1),
        "lag_7": safe_lag(7),
        "lag_14": safe_lag(14),
        "rolling_mean_7": safe_roll(7),
        "rolling_mean_14": safe_roll(14),
    }
    
    

@owner_required
def demand_forecast(request):
    store = get_owner_store(request)

    sku = (request.GET.get("sku") or "").strip()
    action = (request.GET.get("action") or "").strip().lower()

    #  Date range inputs
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    today = date.today()
    default_start = today
    default_end = today + timedelta(days=6)

    start_date = parse_date(start_date_str) if start_date_str else default_start
    end_date = parse_date(end_date_str) if end_date_str else default_end

        
    #  Get SKUs from sales
    sales_skus = set(
    SalesRecord.objects.filter(store=store)
    .values_list("product_sku", flat=True)
)

    #  Get SKUs from inventory
    inventory_qs = InventoryItem.objects.filter(store=store)

    inventory_skus = set(
        inventory_qs.values_list("product_sku", flat=True)
    )

    #  Intersection (ONLY valid products)
    valid_skus = sales_skus.intersection(inventory_skus)

    #  Build dropdown options from inventory (better names)
    sku_options = []
    for item in inventory_qs:
        if item.product_sku in valid_skus:
            sku_options.append({
                "product_sku": item.product_sku,
                "product_name": item.product_name,
            })

    # Sort nicely
    sku_options = sorted(sku_options, key=lambda x: x["product_sku"])

    # Build a sku→name lookup for the result header
    sku_name_map = {p["product_sku"]: p["product_name"] for p in sku_options}
    sku_name = sku_name_map.get(sku, "")

    # output containers
    forecast_rows = []
    chart_labels, chart_pred, chart_low, chart_high = [], [], [], []
    avg_conf = 0

    # -------- Generate forecast for date range --------
    print("==== FORECAST CLICKED ====")
    print("SKU:", sku)
    print("start_date_str:", start_date_str, "end_date_str:", end_date_str)
    print("parsed:", start_date, end_date)

    if sku and action == "generate":
        if not start_date or not end_date:
            messages.error(request, "Please select both Start Date and End Date.")
        elif end_date < start_date:
            messages.error(request, "End Date must be after Start Date.")
        else:
            days_count = (end_date - start_date).days + 1
            if days_count > 90:
                messages.error(request, "Please select a date range within 90 days.")
            else:
                # Step 1: Aggregate daily series 
                hist_qs = (
                    SalesRecord.objects
                    .filter(store=store, product_sku=sku)
                    .values("date")
                    .annotate(daily_qty=Sum("quantity"))
                    .order_by("date")
                )
                hist_days  = list(hist_qs)
                hist_count = len(hist_days)
                series     = [float(r["daily_qty"]) for r in hist_days][-120:]
                print(f"[FORECAST] SKU={sku} | daily days={hist_count} | series len={len(series)}")

                #  Get last known price 
                last_price = 0.0
                try:
                    inv_item = InventoryItem.objects.filter(store=store, product_sku=sku).first()
                    if inv_item and hasattr(inv_item, 'price') and inv_item.price:
                        last_price = float(inv_item.price)
                except Exception:
                    last_price = 0.0

                # ---- Step 2: Determine tier ----
                forecast_warning = None
                use_baseline     = False

                if RF_MODEL is None:
                    use_baseline = True
                    forecast_warning = "Model not loaded. Using baseline (average) forecast."
                elif hist_count < 14:
                    use_baseline = True
                    forecast_warning = (
                         f"Only {hist_count} days of sales data available. Using baseline forecast. For better accuracy, upload more historical data.")
                elif hist_count < 40:
                    forecast_warning = (
                        f"Limited history ({hist_count} days). Forecast generated but may be less accurate."
                    )

                # ---- Step 3: Delete old forecasts in range ----
                # latest forecast remains
                ForecastRecord.objects.filter(
                    store=store,
                    product_sku=sku
                ).delete()

                # ---- Step 4: Generate forecasts  ----
                # Baseline: mean of last 7 days 
                baseline_window = series[-7:] if len(series) >= 7 else series
                baseline_val = float(np.mean(baseline_window)) if baseline_window else 1.0

                with transaction.atomic():
                    d = start_date
                    sim_series = list(series)  
                    while d <= end_date:
                        low = high = None

                        if use_baseline or not series:
                            # Simple average baseline
                            y_pred = baseline_val
                            conf   = 0.50
                        else:
                            # New RF model path
                            product_id = sum([ord(c) for c in sku]) % 10000
                            store_id_enc = store.id % 10

                            feat = _build_feature_row(sim_series, d, product_id, store_id_enc, last_price)
                            Xdf  = pd.DataFrame(
                                [[feat.get(c, 0) for c in FEATURE_COLS]],
                                columns=FEATURE_COLS
                            )

                            y_pred = float(RF_MODEL.predict(Xdf)[0])
                            y_pred = max(y_pred, 0)   # predictions are direct qty 
                            conf   = 0.75

                            # Per-tree confidence interval
                            if hasattr(RF_MODEL, "estimators_"):
                                tree_preds = np.array(
                                    [float(est.predict(Xdf)[0]) for est in RF_MODEL.estimators_],
                                    dtype=float
                                )
                                std  = float(tree_preds.std())
                                mean = float(tree_preds.mean())
                                low  = max(mean - 1.96 * std, 0)
                                high = mean + 1.96 * std
                                denom = abs(mean) if abs(mean) > 1e-6 else 1.0
                                conf  = float(np.clip(1.0 / (1.0 + (std / denom)), 0.0, 1.0))

                        # Save to DB
                        ForecastRecord.objects.create(
                            store=store, product_sku=sku,
                            date=d, predicted_qty=max(y_pred, 0), confidence=conf,
                        )

                        forecast_rows.append({"date": d, "pred": round(y_pred, 2), "conf": round(conf, 2)})
                        chart_labels.append(d.strftime("%b %d, %Y"))
                        chart_pred.append(round(max(y_pred, 0), 2))
                        if low is not None and high is not None:
                            chart_low.append(round(low, 2))
                            chart_high.append(round(high, 2))

                        sim_series.append(max(y_pred, 0))  
                        d = d + timedelta(days=1)

                success_msg = f"Forecast generated for {sku} ({days_count} days)."
                if forecast_warning:
                    messages.warning(request, forecast_warning)
                messages.success(request, success_msg)

                ForecastCounter.objects.create(
                     store=store,
                       
                )

    # Always show saved forecasts for selected range
    if sku:
        range_fc = ForecastRecord.objects.filter(
            store=store,
            product_sku=sku,
            date__gte=start_date,
            date__lte=end_date
        ).order_by("date")

        count = range_fc.count()
        if count:
            conf_sum = range_fc.aggregate(s=Sum("confidence"))["s"] or 0
            avg_conf = (conf_sum / count) if count else 0

        
        if action != "generate":
            for r in range_fc:
                forecast_rows.append({
                    "date": r.date,
                    "pred": round(float(r.predicted_qty), 2),
                    "conf": round(float(r.confidence), 2),
                })
                chart_labels.append(r.date.strftime("%b %d, %Y"))
                chart_pred.append(round(float(r.predicted_qty), 2))

    # ----------------------------
    #  Build insights for UI
    # ----------------------------
    total_demand = 0
    avg_daily = 0
    peak_day = "-"
    peak_value = 0
    recommendation_text = "Generate a forecast to see recommendations."
    avg_conf_pct = int(round(avg_conf * 100)) if avg_conf else 0

    if sku and forecast_rows:
        preds = [int(r["pred"]) if isinstance(r["pred"], (int, float)) else int(float(r["pred"])) for r in forecast_rows]
        dates = [r["date"] for r in forecast_rows]
        confs = [float(r["conf"]) for r in forecast_rows]

        total_demand = int(round(sum(preds)))
        avg_daily = int(round(total_demand / max(len(preds), 1)))

        # peak
        peak_idx = max(range(len(preds)), key=lambda i: preds[i])
        peak_value = int(preds[peak_idx])
        peak_day = dates[peak_idx].strftime("%b %d")

        # current stock (InventoryItem)
        inv = InventoryItem.objects.filter(store=store, product_sku=sku).first()
        current_stock = int(inv.current_stock) if inv and inv.current_stock is not None else 0


        need_units = max(total_demand - current_stock, 0)

        if need_units > 0:
            recommendation_text = (
                f"Based on forecast, you need {total_demand} units for this period. "
                f"Current stock: {current_stock} units. "
                f"Order {need_units} units to avoid stock-out."
            )
        else:
            recommendation_text = (
                f"Based on forecast, you need {total_demand} units for this period. "
                f"Current stock: {current_stock} units. "
                f"No urgent order needed."
            )

        # add per-row UI fields: rounded units, status, confidence %
        for i, r in enumerate(forecast_rows):
            pu = int(round(float(r["pred"])))
            cp = int(round(float(r["conf"]) * 100))

            # Status rule: compare vs avg_daily
            if pu >= int(avg_daily * 1.10):
                status = "High"
            elif pu <= int(avg_daily * 0.90):
                status = "Low"
            else:
                status = "Normal"

            r["pred_units"] = pu
            r["conf_pct"] = cp
            r["status"] = status

        # chart: use rounded units only 
        chart_pred[:] = [r["pred_units"] for r in forecast_rows]
        chart_labels[:] = [r["date"].strftime("%b %d, %Y") for r in forecast_rows]

    return render(request, "ownerpanel/forecast.html", {
        "sku": sku,
        "sku_name": sku_name,
        "sku_options": sku_options,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "forecast_rows": forecast_rows,
        "avg_conf": avg_conf,
        "chart_labels": chart_labels,
        "chart_pred": chart_pred,
        "chart_low": chart_low,
        "chart_high": chart_high,
        "total_demand": total_demand,
        "avg_daily": avg_daily,
        "peak_day": peak_day,
        "peak_value": peak_value,
        "recommendation_text": recommendation_text,
        "avg_conf_pct": avg_conf_pct,
        "store": store,
    })


@owner_required
def inventory_status(request):
    store = get_owner_store(request)

    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    # Base queryset
    items_qs = InventoryItem.objects.filter(store=store).order_by("-updated_at")

    if q:
        items_qs = items_qs.filter(
            Q(product_name__icontains=q) | Q(product_sku__icontains=q)
        )

    # Load items 
    items = list(items_qs[:400])

    # ----------------------------
    # Compute status (real-world logic)
    # ----------------------------
    def compute_status(current_stock, reorder_point, safety_stock):
        stock = float(current_stock or 0)   # Fix: use local var, not it.current_stock
        rp = float(reorder_point or 0)
        ss = float(safety_stock or 0)

        # Low if below safety OR below/equal reorder point
        if stock <= ss or (rp > 0 and stock <= rp):
            return "LOW"

        # Overstock if far above reorder point
        elif rp > 0 and stock >= rp * 3:
            return "OVER"

        return "OK"

    # Assign status for UI 
    for it in items:

    #  AUTO CALCULATE if missing
        if not it.reorder_point or not it.safety_stock:

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

                    # 🔥 AUTO VALUES
                    if not it.reorder_point:
                        it.reorder_point = int(avg_daily * 3)

                    if not it.safety_stock:
                        it.safety_stock = int(avg_daily * 1.5)

        
        it.status = compute_status(it.current_stock, it.reorder_point, it.safety_stock)
    # Apply status filter (on computed status)
    if status_filter:
        items = [it for it in items if it.status == status_filter]

    # ----------------------------
    # KPIs based on visible items
    # ----------------------------
    total_items = len(items)

    healthy_count = sum(1 for it in items if it.status == "OK")
    low_count = sum(1 for it in items if it.status == "LOW")
    over_count = sum(1 for it in items if it.status == "OVER")

    # "Critical" means stock is 0 (optional)
    critical_count = sum(1 for it in items if float(it.current_stock or 0) == 0)

    health_score = int((healthy_count / total_items) * 100) if total_items else 0

    return render(request, "ownerpanel/inventory.html", {
        "items": items,
        "q": q,
        "status": status_filter,
        "store": store,
        "health_score": health_score,
        "healthy_count": healthy_count,
        "low_count": low_count,
        "critical_count": critical_count,
        "over_count": over_count,
    })

# # ---------------------------
# API for Chart.js
# ---------------------------
from datetime import date, timedelta
from django.http import JsonResponse

@owner_required
def api_demand_chart(request):
    store = get_owner_store(request)
    sku = request.GET.get("sku", "").strip()
    days = int(request.GET.get("days", "30"))

    end = date.today()
    start = end - timedelta(days=days - 1)

    sales_qs = SalesRecord.objects.filter(store=store, date__range=(start, end))
    fc_qs = ForecastRecord.objects.filter(store=store, date__range=(start, end))

    if sku:
        sales_qs = sales_qs.filter(product_sku=sku)
        fc_qs = fc_qs.filter(product_sku=sku)

    # --- aggregate sales per day ---
    sales_map = {}
    for r in sales_qs:
        sales_map[r.date] = sales_map.get(r.date, 0) + float(r.quantity)

    # --- aggregate forecast per day (if exists for same dates) ---
    fc_map = {}
    for r in fc_qs:
        
        val = float(getattr(r, "predicted_qty", None) or getattr(r, "forecast_qty", 0) or 0)
        fc_map[r.date] = fc_map.get(r.date, 0) + val

    # build continuous date list
    all_dates = []
    d = start
    while d <= end:
        all_dates.append(d)
        d += timedelta(days=1)

    labels = [d.strftime("%Y-%m-%d") for d in all_dates]

    # Actual values aligned
    actual = [round(sales_map.get(d, 0), 2) for d in all_dates]

    
    predicted = []
    for i, d in enumerate(all_dates):
        if d in fc_map:
            predicted.append(round(fc_map[d], 2))
            continue

        # rolling average of previous 7 days actual
        window = actual[max(0, i-7):i]
        if len(window) == 0:
            predicted.append(None)
        else:
            predicted.append(round(sum(window) / len(window), 2))

    return JsonResponse({
        "labels": labels,
        "actual": actual,
        "predicted": predicted,
    })

from django.views.decorators.http import require_POST
from django.shortcuts import redirect
from django.contrib import messages

@owner_required
@require_POST
def clear_upload_history(request):
    store = get_owner_store(request)

    # Delete only one store's upload history
    DataUpload.objects.filter(store=store).delete()

    messages.success(request, "Upload history cleared successfully.")
    return redirect("ownerpanel:upload")   

# ===========================
# ALERTS HELPERS
# ===========================

def _create_or_update_alert(
    store,
    product_sku,
    product_name,
    alert_type,
    severity,
    title,
    message,
    current_stock,
    threshold,
):
    # Only ACTIVE alert 
    alert = Alert.objects.filter(
        store=store,
        product_sku=product_sku,
        alert_type=alert_type
    ).order_by("-created_at").first()


    if alert and alert.is_resolved:
        return alert

    if alert:
       
        alert.product_name = product_name
        alert.severity = severity
        alert.title = title
        alert.message = message
        alert.current_stock = current_stock
        alert.threshold = threshold
        alert.save()
        return alert

    #  Create new alert 
    return Alert.objects.create(
        store=store, 
        product_sku=product_sku,
        product_name=product_name,
        alert_type=alert_type,
        severity=severity,
        title=title,
        message=message,
        current_stock=current_stock,
        threshold=threshold,
        is_resolved=False,
        is_read=False,
    )

from django.utils import timezone

def _resolve_alert_if_exists(store, product_sku, alert_type):
    """
    Resolve existing alert if inventory is healthy now.
    """

    Alert.objects.filter(
        store=store,
        product_sku=product_sku,
        alert_type=alert_type,
        is_resolved=False
    ).update(
        is_resolved=True,
        is_read=True,
        resolved_at=timezone.now()
    )
    
    
from django.utils import timezone

def sync_inventory_alerts(store):

    items = InventoryItem.objects.filter(store=store)
    valid_skus = set(items.values_list("product_sku", flat=True))

    
    Alert.objects.filter(store=store).exclude(
        product_sku__in=valid_skus
    ).update(
        is_resolved=True,
        resolved_at=timezone.now()
    )

    for item in items:

        stock = float(item.current_stock or 0)
        reorder = float(item.reorder_point or 0)
        safety = float(item.safety_stock or 0)

        # AUTO CALCULATE
        if not reorder or not safety:
            sales = SalesRecord.objects.filter(
                store=store,
                product_sku=item.product_sku
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

        # LOW STOCK — same condition as inventory page: below safety OR below/equal reorder
        if stock <= safety or (reorder > 0 and stock <= reorder):
            _create_or_update_alert(
                store=store,
                product_sku=item.product_sku,
                product_name=item.product_name,
                alert_type="LOW_STOCK",
                severity="WARN",
                title=f"Low Stock - {item.product_name}",
                message=f"{item.product_name} ({item.product_sku}) is below reorder level. Current stock: {stock}",
                current_stock=stock,
                threshold=reorder,
            )

            _resolve_alert_if_exists(store, item.product_sku, "OVERSTOCK")

        # OVERSTOCK
        elif reorder > 0 and stock >= (reorder * 3):
            _create_or_update_alert(
                store=store,
                product_sku=item.product_sku,
                product_name=item.product_name,
                alert_type="OVERSTOCK",
                severity="INFO",
                title=f"Overstock - {item.product_name}",
                message=f"{item.product_name} ({item.product_sku}) has excess inventory. Current stock: {stock}",
                current_stock=stock,
                threshold=reorder * 3,
            )

            _resolve_alert_if_exists(store, item.product_sku, "LOW_STOCK")

        
        else:
            _resolve_alert_if_exists(store, item.product_sku, "LOW_STOCK")
            _resolve_alert_if_exists(store, item.product_sku, "OVERSTOCK")
# ===========================
# ALERTS PAGE
# ===========================
@owner_required
def alerts_page(request):
    store = get_owner_store(request)

    # Always sync alerts with latest inventory first
    sync_inventory_alerts(store)

    tab = request.GET.get("tab", "all")
    sort = request.GET.get("sort", "new")

    

    alerts_qs = Alert.objects.filter(
        store=store,
        is_resolved=False
    )

    # Simplified filters
    if tab == "low":
        alerts_qs = alerts_qs.filter(alert_type="LOW_STOCK")
    elif tab == "overstock":
        alerts_qs = alerts_qs.filter(alert_type="OVERSTOCK")

    # Sorting
    if sort == "old":
        alerts_qs = alerts_qs.order_by("created_at")
    else:
        alerts_qs = alerts_qs.order_by("-created_at")

    # Summary counts
    total_count = Alert.objects.filter(
        store=store,
        is_resolved=False
    ).count()

    low_count = Alert.objects.filter(
        store=store,
        alert_type="LOW_STOCK",
        is_resolved=False
    ).count()

    overstock_count = Alert.objects.filter(
        store=store,
        alert_type="OVERSTOCK",
        is_resolved=False
    ).count()

    context = {
        "store": store,
        "alerts": alerts_qs,
        "tab": tab,
        "sort": sort,
        "total_count": total_count,
        "low_count": low_count,
        "overstock_count": overstock_count,
    }
    return render(request, "ownerpanel/alerts.html",context)

@owner_required
def resolve_alert(request, alert_id):
    alert = get_object_or_404(Alert, id=alert_id)

    alert.is_resolved = True
    alert.save()

    return redirect("ownerpanel:alerts_page")  # change if your url name is different


@owner_required
def alert_read(request, alert_id):
    alert = get_object_or_404(Alert, id=alert_id)
    alert.is_read = True
    alert.save(update_fields=["is_read"])

    messages.success(request, "Alert marked as read.")
    return redirect("ownerpanel:alerts")

# ==========================================
# REPORTS HELPERS
# ==========================================

def _parse_reports_date_range(request):
    """
    Parse and validate reports date range.
    Defaults to last 30 days.
    Max range allowed = 365 days.
    """
    today = date.today()
    default_start = today - timedelta(days=29)
    default_end = today

    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    start_date = parse_date(start_date_str) if start_date_str else default_start
    end_date = parse_date(end_date_str) if end_date_str else default_end

    if not start_date or not end_date:
        return None, None, "Please enter valid start and end dates."

    if end_date < start_date:
        return None, None, "End date must be after or equal to start date."

    if (end_date - start_date).days > 365:
        return None, None, "Maximum allowed date range is 1 year."

    return start_date, end_date, None


# ==========================================
# REPORTS PAGE
# ==========================================

@owner_required
def reports_page(request):
    store = get_owner_store(request)

    start_date, end_date, error = _parse_reports_date_range(request)
    if error:
        messages.error(request, error)
        today = date.today()
        start_date = today - timedelta(days=29)
        end_date = today

    store_data = calculate_store_performance_data(store, start_date, end_date)
    inventory_data = calculate_inventory_report_data(store, start_date, end_date)

    return render(request, "ownerpanel/reports.html", {
        "store": store,
        "start_date": start_date,
        "end_date": end_date,
        "store_report": store_data,
        "inventory_report": inventory_data,
    })


# ==========================================
# DOWNLOAD STORE PERFORMANCE PDF
# ==========================================

@owner_required
def download_store_performance(request):
    store = get_owner_store(request)

# Try to get from request first
    from django.utils.dateparse import parse_date

    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    start_date = parse_date(start_date) if start_date else None
    end_date = parse_date(end_date) if end_date else None

    #  If not provided → fallback to latest forecast data
    if not start_date or not end_date:
        forecasts = ForecastRecord.objects.filter(store=store).order_by("date")

        if forecasts.exists():
            start_date = forecasts.first().date
            end_date = forecasts.last().date
        else:
            return HttpResponse("Please generate forecast first to download report", status=400)

    report_data = calculate_store_performance_data(store, start_date, end_date)
    pdf_content = build_store_performance_pdf(store, report_data)

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S") 
    filename = f"StoreForecastReport_{timestamp}.pdf"

    ReportRun.objects.create(
        store=store,
        title=f"Store Forecast Report ({start_date} to {end_date})",
        status="DONE",
    )

    response = HttpResponse(pdf_content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

# ==========================================
# DOWNLOAD INVENTORY PDF
# ==========================================

@owner_required
def download_inventory(request):
    store = get_owner_store(request)

    today = timezone.localdate()
    start_date = today.replace(day=1)

    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)

    end_date = next_month - timedelta(days=1)

    report_data = calculate_inventory_report_data(store, start_date, end_date)
    pdf_content = build_inventory_pdf(store, report_data)

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    filename = f"InventoryReport_{timestamp}.pdf"

    ReportRun.objects.create(
        store=store,
        title=f"Inventory Report ({start_date} to {end_date})",
        status="DONE",
    )

    response = HttpResponse(pdf_content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

def _get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _log_activity(request, activity_type, description, metadata=None):
    if request.user.is_authenticated:
        ActivityLog.objects.create(
            user=request.user,
            activity_type=activity_type,
            description=description,
            ip_address=_get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            metadata=metadata or {},
        )


def _get_or_create_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


@login_required
def profile(request):
    store = get_owner_store(request)
    profile = _get_or_create_profile(request.user)

    if not profile.store:
        try:
            owner_store = get_owner_store(request)
            profile.store = owner_store
            profile.save(update_fields=["store"])
        except Exception:
            pass

    profile.last_active = timezone.now()
    profile.save(update_fields=["last_active"])

    profile_form = ProfileForm(instance=profile, user=request.user)
    photo_form = ProfilePhotoForm(instance=profile)
    settings_form = AccountSettingsForm(instance=profile)
    password_form = CustomPasswordChangeForm(user=request.user)

    activity_qs = ActivityLog.objects.filter(user=request.user).order_by("-timestamp")
    paginator = Paginator(activity_qs, 8)
    page_number = request.GET.get("page")
    activity_page = paginator.get_page(page_number)

    total_products = InventoryItem.objects.filter(store=profile.store).count() if profile.store else 0
    total_forecasts =ForecastCounter.objects.filter(store=store).count() if profile.store else 0
    total_reports = ReportRun.objects.filter(store=profile.store).count() if profile.store else 0
    total_uploads = DataUpload.objects.filter(store=profile.store).count() if profile.store else 0

    context = {
        "store": store,
        "profile_obj": profile,
        "profile_form": profile_form,
        "photo_form": photo_form,
        "settings_form": settings_form,
        "password_form": password_form,
        "activity_page": activity_page,
        "store_stats": {
            "total_products": total_products,
            "total_forecasts": total_forecasts,
            "total_reports": total_reports,
            "total_uploads": total_uploads,
            "account_status": "Active" if request.user.is_active else "Inactive",
            "subscription_plan": "Academic Project",
        }
    }
    return render(request, "ownerpanel/profile.html", context)


@login_required
def update_profile(request):
    if request.method != "POST":
        return redirect("ownerpanel:profile")

    profile = _get_or_create_profile(request.user)
    form = ProfileForm(request.POST, instance=profile, user=request.user)

    if form.is_valid():
        request.user.first_name = form.cleaned_data["full_name"].strip()
        request.user.email = form.cleaned_data["email"].strip()
        request.user.save()

        form.save()

        _log_activity(
            request,
            "PROFILE_UPDATE",
            "Profile information updated",
            {"email": request.user.email}
        )

        messages.success(request, "Profile updated successfully.")
    else:
        messages.error(request, "Please correct the errors in the profile form.")

    return redirect("ownerpanel:profile")


@login_required
def upload_photo(request):
    if request.method != "POST":
        return redirect("ownerpanel:profile")

    profile = _get_or_create_profile(request.user)
    form = ProfilePhotoForm(request.POST, request.FILES, instance=profile)

    if form.is_valid():
        form.save()
        _log_activity(request, "PROFILE_UPDATE", "Profile photo updated")
        messages.success(request, "Profile photo updated successfully.")
    else:
        messages.error(request, "Invalid image. Please upload JPG, PNG, or WEBP under 5MB.")

    return redirect("ownerpanel:profile")


@login_required
def update_account_settings(request):
    if request.method != "POST":
        return redirect("ownerpanel:profile")

    profile = _get_or_create_profile(request.user)
    form = AccountSettingsForm(request.POST, instance=profile)

    if form.is_valid():
        form.save()
        _log_activity(request, "SETTINGS_UPDATE", "Account settings updated")
        messages.success(request, "Account settings updated successfully.")
    else:
        messages.error(request, "Unable to update settings. Please check your inputs.")

    return redirect("ownerpanel:profile")


@login_required
def change_password(request):
    if request.method != "POST":
        return redirect("ownerpanel:profile")

    form = CustomPasswordChangeForm(user=request.user, data=request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)

        _log_activity(request, "PASSWORD_CHANGE", "Password changed successfully")
        messages.success(request, "Password changed successfully.")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)

    return redirect("ownerpanel:profile")


@login_required
def activity_history(request):
    activity_qs = ActivityLog.objects.filter(user=request.user).order_by("-timestamp")
    paginator = Paginator(activity_qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    rows = []
    for item in page_obj:
        rows.append({
            "type": item.activity_type,
            "description": item.description,
            "ip_address": item.ip_address,
            "timestamp": item.timestamp.strftime("%d %b %Y, %I:%M %p"),
        })

    return JsonResponse({
        "items": rows,
        "has_next": page_obj.has_next(),
        "has_previous": page_obj.has_previous(),
        "page": page_obj.number,
    })
