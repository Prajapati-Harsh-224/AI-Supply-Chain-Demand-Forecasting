from io import BytesIO
from datetime import timedelta
from django.db.models import Sum, Avg, Count
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)

from ownerpanel.models import SalesRecord, InventoryItem, ForecastRecord


def _safe_div(a, b):
    return round((a / b), 2) if b else 0


def _daterange_days(start_date, end_date):
    return max((end_date - start_date).days + 1, 1)


def _get_sales_qs(store, start_date, end_date):
    return SalesRecord.objects.filter(
        store=store,
        date__gte=start_date,
        date__lte=end_date
    )


def _get_forecast_qs(store, start_date, end_date):
    return ForecastRecord.objects.filter(
        store=store,
        date__gte=start_date,
        date__lte=end_date
    )


# =========================================================
# STORE FORECAST REPORT DATA
# =========================================================
def calculate_store_performance_data(store, start_date, end_date):
    """
    Forecast-based report data for selected date range.
    This matches your project better than sales analytics.
    """

    forecast_qs = _get_forecast_qs(store, start_date, end_date).order_by("product_sku", "date")
    inventory_qs = InventoryItem.objects.filter(store=store)

    # Basic summary
    forecast_count = forecast_qs.count()
    product_count = forecast_qs.values("product_sku").distinct().count()

    total_predicted_demand = forecast_qs.aggregate(
        total=Sum("predicted_qty")
    ).get("total") or 0

    avg_predicted_demand = forecast_qs.aggregate(
        avg=Avg("predicted_qty")
    ).get("avg") or 0

    avg_confidence = forecast_qs.aggregate(
        avg=Avg("confidence")
    ).get("avg") or 0

    peak_record = forecast_qs.order_by("-predicted_qty").first()

    # Inventory names
    sku_name_map = {
        item.product_sku: item.product_name
        for item in inventory_qs
    }

    # Product-wise forecast summary 
    product_summary = []

    #  get unique SKUs using Python set
    sku_groups = list(set(forecast_qs.values_list("product_sku", flat=True)))

    for sku in sku_groups:
        sku_rows = list(
            forecast_qs.filter(product_sku=sku).order_by("date")
        )
        
        if sku_rows:
            start_date = sku_rows[0].date
            end_date = sku_rows[-1].date
            date_range = f"{start_date.strftime('%d-%m-%Y')} To {end_date.strftime('%d-%m-%Y')}"
        else:
            date_range = "-"

        
        daily_int_preds = [int(float(r.predicted_qty or 0)) for r in sku_rows]
        total_forecast = int(round(sum(daily_int_preds)))

        avg_conf_pct = int(round(
            sum(float(r.confidence or 0) for r in sku_rows) / len(sku_rows) * 100
        )) if sku_rows else 0

        forecast_days = len(sku_rows)

        product_summary.append({
            "product_sku": sku,
            "product_name": sku_name_map.get(sku, ""),
            "total_forecast": max(0, total_forecast),
            "avg_conf_pct": max(0, avg_conf_pct),
            "forecast_days": forecast_days,
            "date_range": date_range,
        })

    
    product_summary.sort(key=lambda x: x["total_forecast"], reverse=True)
    
    # Detailed rows
    detail_rows = []
    for row in forecast_qs:
        detail_rows.append({
            "date": row.date,
            "product_sku": row.product_sku,
            "product_name": sku_name_map.get(row.product_sku, ""),
            "predicted_qty": max(0, int(float(row.predicted_qty or 0))),
            "confidence_pct": round(float((row.confidence or 0) * 100), 0),
        })

    # Forecast coverage
    min_fc_date = forecast_qs.order_by("date").values_list("date", flat=True).first()
    max_fc_date = forecast_qs.order_by("-date").values_list("date", flat=True).first()

    # Recommendation
    if forecast_count == 0:
        recommendation_text = (
            "No forecast data is available for the selected date range. "
            "Please generate forecast first from the Demand Forecast page."
        )
    else:
        recommendation_text = (
            f"{product_count} product(s) have forecast data in the selected period. "
            f"Total predicted demand is {round(float(total_predicted_demand), 2)} units. "
            "Use this summary report to plan stock availability and monitor forecast coverage for the selected period."
        )

    return {
    "store_name": store.name,
    "start_date": start_date,
    "end_date": end_date,
    "generated_at": timezone.localtime(),

    "forecast_count": forecast_count,
    "product_count": product_count,
   "total_predicted_demand": max(0, int(round(sum(int(float(r.predicted_qty or 0)) for r in forecast_qs)))),
    "avg_predicted_demand": max(0, int(round(
        sum(int(float(r.predicted_qty or 0)) for r in forecast_qs) / forecast_count
    ))) if forecast_count else 0,
    "avg_confidence_pct": max(0, int(round(float(avg_confidence * 100)))),

    "peak_date": peak_record.date if peak_record else None,
    "peak_sku": peak_record.product_sku if peak_record else "-",
    "peak_product_name": sku_name_map.get(peak_record.product_sku, "") if peak_record else "",
    "peak_value": max(0, int(float(peak_record.predicted_qty or 0))) if peak_record else 0,

    "coverage_start": min_fc_date,
    "coverage_end": max_fc_date,

    "product_summary": product_summary,
    "detail_rows": detail_rows,

    "note": "This report is based on saved forecast records available in the selected date range.",
    "recommendation_text": recommendation_text,
}


# =========================================================
# INVENTORY REPORT DATA
# =========================================================
from django.db.models import Min, Max, Sum
def calculate_inventory_report_data(store, start_date, end_date):
    """
    Inventory report using your real models.
    """
    inventory_qs = InventoryItem.objects.filter(store=store).order_by("product_name")
    sales_qs = _get_sales_qs(store, start_date, end_date)
    forecast_qs = _get_forecast_qs(store, start_date, end_date)

    rows = []
    total_current_stock = 0
    total_reorder_qty = 0
    low_stock_count = 0
    critical_count = 0
    overstock_count = 0

    for item in inventory_qs:
        sku = item.product_sku
        stock = float(item.current_stock or 0)
        reorder = float(item.reorder_point or 0)
        safety = float(item.safety_stock or 0)

    

# AUTO CALCULATE 
        if not reorder or not safety:
            sales = SalesRecord.objects.filter(
                store=store,
                product_sku=sku
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
                        reorder = int(avg_daily * 3)   # your SaaS logic

                    if not safety:
                        safety = int(avg_daily * 1.5)


        total_current_stock += stock

        sold_total = (
            sales_qs.filter(product_sku=sku)
            .aggregate(total=Sum("quantity"))
            .get("total") or 0
        )

        total_days = _daterange_days(start_date, end_date)
        avg_daily_sales = round(float(sold_total) / total_days, 2) if total_days else 0

        next_7_days_forecast = (
            forecast_qs.filter(
                product_sku=sku,
                date__gte=start_date,
                date__lte=min(end_date, start_date + timedelta(days=6))
            )
            .aggregate(total=Sum("predicted_qty"))
            .get("total") or 0
        )

        reorder_qty = max(round(float(next_7_days_forecast) - stock + safety), 0)
        total_reorder_qty += reorder_qty

        
        if reorder > 0 and stock < reorder:
            status = "Low Stock"
            low_stock_count += 1
        elif reorder > 0 and stock >= (reorder * 3):
            status = "Overstock"
            overstock_count += 1
        else:
            status = "Healthy"

        days_of_inventory = round(stock / avg_daily_sales, 2) if avg_daily_sales > 0 else 0
        turnover_proxy = round((float(sold_total) / stock), 2) if stock > 0 else 0

        rows.append({
            "sku": sku,
            "product_name": item.product_name,
            "current_stock": int(stock),
            "reorder_point": int(reorder),
            "safety_stock": int(safety),
            "avg_daily_sales": avg_daily_sales,
            "forecast_next_7_days": round(float(next_7_days_forecast), 2),
            "days_of_inventory": days_of_inventory,
            "reorder_qty": reorder_qty,
            "turnover_proxy": turnover_proxy,
            "status": status,
        })

    return {
        "store_name": store.name,
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": timezone.localtime(),
        "total_skus": len(rows),
        "total_current_stock": int(total_current_stock),
        "total_reorder_qty": int(total_reorder_qty),
        "low_stock_count": low_stock_count,
        "critical_count": critical_count,
        "overstock_count": overstock_count,
        "rows": rows,
        "note": "Inventory report combines current stock data with available forecast records for the selected period.",
    }


def _build_pdf_header(story, styles, title, subtitle):
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph(subtitle, styles["Normal"]))
    story.append(Spacer(1, 0.25 * inch))


def _styled_table(data, col_widths=None):
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dbe4f0")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


# =========================================================
# STORE FORECAST PDF
# =========================================================
def build_store_performance_pdf(store, report_data):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallMuted", fontSize=9, textColor=colors.grey))

    story = []

    report_period = report_data["generated_at"].strftime("%B %Y")

    subtitle = (
    f"Store: {report_data['store_name']} | "
    f"Report Period: {report_period} | "
    f"Generated: {report_data['generated_at'].strftime('%d %b %Y, %I:%M %p')}"
)

    _build_pdf_header(story, styles, "Store Forecast Report", subtitle)

    table_data = [["SKU", "Product Name", "Total Forecast", "Forecast Days",  "Forecast Range"]]

    for item in report_data["product_summary"]:
        table_data.append([
            item.get("product_sku", "-"),
            item.get("product_name") or "-",
            str(item.get("total_forecast", 0)),
            str(item.get("forecast_days", 0)),
            item.get("date_range", "-"),
        ])

    if len(table_data) == 1:
        table_data.append(["-", "No forecast data available", "-", "-"])

    story.append(_styled_table(table_data, col_widths=[80, 200, 90, 80, 120]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(report_data["note"], styles["SmallMuted"]))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

# =========================================================
# INVENTORY PDF
# =========================================================
def build_inventory_pdf(store, report_data):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallMuted", fontSize=9, textColor=colors.grey))

    story = []

    report_period = report_data["generated_at"].strftime("%B %Y")

    subtitle = (
        f"Store: {report_data['store_name']} | "
        f"Report Period: {report_period} | "
        f"Generated: {report_data['generated_at'].strftime('%d %b %Y, %I:%M %p')}"
    )

    _build_pdf_header(story, styles, "Inventory Report", subtitle)

    table_data = [["SKU", "Product Name", "Stock", "Reorder", "Safety", "Status"]]

    for row in report_data["rows"]:
        table_data.append([
            row["sku"],
            row["product_name"] or "-",
            str(row["current_stock"]),
            str(row["reorder_point"]),
            str(row["safety_stock"]),
            row["status"],
        ])

    if len(table_data) == 1:
        table_data.append(["-", "No inventory data available", "-", "-", "-", "-"])

    story.append(_styled_table(
        table_data,
        col_widths=[80, 210, 60, 70, 70, 70]
    ))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("This report shows the current inventory snapshot for the store.", styles["SmallMuted"]))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf